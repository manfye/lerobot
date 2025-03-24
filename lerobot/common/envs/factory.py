#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import importlib
from collections import deque

import gymnasium as gym

from lerobot.common.envs.configs import AlohaEnv, EnvConfig, PushtEnv, XarmEnv


def make_env_config(env_type: str, **kwargs) -> EnvConfig:
    if env_type == "aloha":
        return AlohaEnv(**kwargs)
    elif env_type == "pusht":
        return PushtEnv(**kwargs)
    elif env_type == "xarm":
        return XarmEnv(**kwargs)
    else:
        raise ValueError(f"Policy type '{env_type}' is not available.")


def make_env(
    cfg: EnvConfig, n_envs: int = 1, use_async_envs: bool = False
) -> gym.vector.VectorEnv | None:
    """Makes a gym vector environment according to the config.

    Args:
        cfg (EnvConfig): the config of the environment to instantiate.
        n_envs (int, optional): The number of parallelized env to return. Defaults to 1.
        use_async_envs (bool, optional): Whether to return an AsyncVectorEnv or a SyncVectorEnv. Defaults to
            False.

    Raises:
        ValueError: if n_envs < 1
        ModuleNotFoundError: If the requested env package is not installed

    Returns:
        gym.vector.VectorEnv: The parallelized gym.env instance.
    """
    if n_envs < 1:
        raise ValueError("`n_envs must be at least 1")

    package_name = f"gym_{cfg.type}"

    try:
        importlib.import_module(package_name)
    except ModuleNotFoundError as e:
        print(
            f"{package_name} is not installed. Please install it with `pip install 'lerobot[{cfg.type}]'`"
        )
        raise e

    gym_handle = f"{package_name}/{cfg.task}"

    # batched version of the env that returns an observation of shape (b, c)
    env_cls = gym.vector.AsyncVectorEnv if use_async_envs else gym.vector.SyncVectorEnv
    env = env_cls(
        [
            lambda: gym.make(gym_handle, disable_env_checker=True, **cfg.gym_kwargs)
            for _ in range(n_envs)
        ]
    )

    return env


def make_maniskill_env(
    cfg: DictConfig, n_envs: int | None = None
) -> gym.vector.VectorEnv | None:
    """Make ManiSkill3 gym environment"""
    from mani_skill.vector.wrappers.gymnasium import ManiSkillVectorEnv

    env = gym.make(
        cfg.env.task,
        obs_mode=cfg.env.obs,
        control_mode=cfg.env.control_mode,
        render_mode=cfg.env.render_mode,
        sensor_configs=dict(width=cfg.env.image_size, height=cfg.env.image_size),
        num_envs=n_envs,
    )
    # cfg.env_cfg.control_mode = cfg.eval_env_cfg.control_mode = env.control_mode
    env = ManiSkillVectorEnv(env, ignore_terminations=True)
    # state should have the size of 25
    # env = ConvertToLeRobotEnv(env, n_envs)
    # env = PixelWrapper(cfg, env, n_envs)
    env._max_episode_steps = env.max_episode_steps = (
        50  # gym_utils.find_max_episode_steps_value(env)
    )
    env.unwrapped.metadata["render_fps"] = 20

    return env


class PixelWrapper(gym.Wrapper):
    """
    Wrapper for pixel observations. Works with Maniskill vectorized environments
    """

    def __init__(self, cfg, env, num_envs, num_frames=3):
        super().__init__(env)
        self.cfg = cfg
        self.env = env
        self.observation_space = gym.spaces.Box(
            low=0,
            high=255,
            shape=(num_envs, num_frames * 3, cfg.env.render_size, cfg.env.render_size),
            dtype=np.uint8,
        )
        self._frames = deque([], maxlen=num_frames)
        self._render_size = cfg.env.render_size

    def _get_obs(self, obs):
        frame = obs["sensor_data"]["base_camera"]["rgb"].cpu().permute(0, 3, 1, 2)
        self._frames.append(frame)
        return {
            "pixels": torch.from_numpy(np.concatenate(self._frames, axis=1)).to(
                self.env.device
            )
        }

    def reset(self, seed):
        obs, info = self.env.reset()  # (seed=seed)
        for _ in range(self._frames.maxlen):
            obs_frames = self._get_obs(obs)
        return obs_frames, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        return self._get_obs(obs), reward, terminated, truncated, info


# TODO: Remove this
class ConvertToLeRobotEnv(gym.Wrapper):
    def __init__(self, env, num_envs):
        super().__init__(env)

    def reset(self, seed=None, options=None):
        obs, info = self.env.reset(seed=seed, options={})
        return self._get_obs(obs), info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        return self._get_obs(obs), reward, terminated, truncated, info

    def _get_obs(self, observation):
        sensor_data = observation.pop("sensor_data")
        del observation["sensor_param"]
        images = []
        for cam_data in sensor_data.values():
            images.append(cam_data["rgb"])

        images = torch.concat(images, axis=-1)
        # flatten the rest of the data which should just be state data
        observation = common.flatten_state_dict(
            observation, use_torch=True, device=self.base_env.device
        )
        ret = dict()
        ret["state"] = observation
        ret["pixels"] = images
        return ret
