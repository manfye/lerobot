#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team.
# All rights reserved.
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

from dataclasses import dataclass, field

from lerobot.common.optim.optimizers import MultiAdamConfig
from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.types import FeatureType, NormalizationMode, PolicyFeature


@dataclass
class ConcurrencyConfig:
    actor: str = "threads"
    learner: str = "threads"


@dataclass
class ActorLearnerConfig:
    learner_host: str = "127.0.0.1"
    learner_port: int = 50051
    policy_parameters_push_frequency: int = 4


@dataclass
class CriticNetworkConfig:
    hidden_dims: list[int] = field(default_factory=lambda: [256, 256])
    activate_final: bool = True
    final_activation: str | None = None


@dataclass
class ActorNetworkConfig:
    hidden_dims: list[int] = field(default_factory=lambda: [256, 256])
    activate_final: bool = True


@dataclass
class PolicyConfig:
    use_tanh_squash: bool = True
    log_std_min: int = -5
    log_std_max: int = 2
    init_final: float = 0.05


@PreTrainedConfig.register_subclass("sac")
@dataclass
class SACConfig(PreTrainedConfig):
    """Soft Actor-Critic (SAC) configuration.

    SAC is an off-policy actor-critic deep RL algorithm based on the maximum entropy
    reinforcement learning framework. It learns a policy and a Q-function simultaneously
    using experience collected from the environment.

    This configuration class contains all the parameters needed to define a SAC agent,
    including network architectures, optimization settings, and algorithm-specific
    hyperparameters.

    Args:
        actor_network: Configuration for the actor network architecture.
        critic_network: Configuration for the critic network architecture.
        policy: Configuration for the policy parameters.
        n_obs_steps: Number of observation steps to consider.
        normalization_mapping: Mapping of feature types to normalization modes.
        dataset_stats: Statistics for normalizing different types of inputs.
        input_features: Dictionary of input features with their types and shapes.
        output_features: Dictionary of output features with their types and shapes.
        camera_number: Number of cameras used for visual observations.
        device: Device to run the model on (e.g., "cuda", "cpu").
        storage_device: Device to store the model on.
        vision_encoder_name: Name of the vision encoder model.
        freeze_vision_encoder: Whether to freeze the vision encoder during training.
        image_encoder_hidden_dim: Hidden dimension size for the image encoder.
        shared_encoder: Whether to use a shared encoder for actor and critic.
        concurrency: Configuration for concurrency settings.
        actor_learner: Configuration for actor-learner architecture.
        online_steps: Number of steps for online training.
        online_env_seed: Seed for the online environment.
        online_buffer_capacity: Capacity of the online replay buffer.
        offline_buffer_capacity: Capacity of the offline replay buffer.
        online_step_before_learning: Number of steps before learning starts.
        policy_update_freq: Frequency of policy updates.
        discount: Discount factor for the SAC algorithm.
        temperature_init: Initial temperature value.
        num_critics: Number of critics in the ensemble.
        num_subsample_critics: Number of subsampled critics for training.
        critic_lr: Learning rate for the critic network.
        actor_lr: Learning rate for the actor network.
        temperature_lr: Learning rate for the temperature parameter.
        critic_target_update_weight: Weight for the critic target update.
        utd_ratio: Update-to-data ratio for the UTD algorithm.
        state_encoder_hidden_dim: Hidden dimension size for the state encoder.
        latent_dim: Dimension of the latent space.
        target_entropy: Target entropy for the SAC algorithm.
        use_backup_entropy: Whether to use backup entropy for the SAC algorithm.
        grad_clip_norm: Gradient clipping norm for the SAC algorithm.
    """

    normalization_mapping: dict[str, NormalizationMode] = field(
        default_factory=lambda: {
            "VISUAL": NormalizationMode.MEAN_STD,
            "STATE": NormalizationMode.MIN_MAX,
            "ENV": NormalizationMode.MIN_MAX,
            "ACTION": NormalizationMode.MIN_MAX,
        }
    )

    dataset_stats: dict[str, dict[str, list[float]]] = field(
        default_factory=lambda: {
            "observation.image": {
                "mean": [0.485, 0.456, 0.406],
                "std": [0.229, 0.224, 0.225],
            },
            "observation.state": {
                "min": [0.0, 0.0],
                "max": [1.0, 1.0],
            },
            "action": {
                "min": [0.0, 0.0, 0.0],
                "max": [1.0, 1.0, 1.0],
            },
        }
    )

    input_features: dict[str, PolicyFeature] = field(
        default_factory=lambda: {
            "observation.image": PolicyFeature(type=FeatureType.VISUAL, shape=(3, 64, 64)),
            "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(2,)),
        }
    )
    output_features: dict[str, PolicyFeature] = field(
        default_factory=lambda: {
            "action": PolicyFeature(type=FeatureType.ACTION, shape=(3,)),
        }
    )

    # Architecture specifics
    camera_number: int = 1
    device: str = "cuda"
    storage_device: str = "cpu"
    # Set to "helper2424/resnet10" for hil serl
    vision_encoder_name: str | None = None
    freeze_vision_encoder: bool = True
    image_encoder_hidden_dim: int = 32
    shared_encoder: bool = True

    # Training parameter
    online_steps: int = 1000000
    online_env_seed: int = 10000
    online_buffer_capacity: int = 100000
    offline_buffer_capacity: int = 100000
    online_step_before_learning: int = 100
    policy_update_freq: int = 1

    # SAC algorithm parameters
    discount: float = 0.99
    temperature_init: float = 1.0
    num_critics: int = 2
    num_subsample_critics: int | None = None
    critic_lr: float = 3e-4
    actor_lr: float = 3e-4
    temperature_lr: float = 3e-4
    critic_target_update_weight: float = 0.005
    utd_ratio: int = 1  # If you want enable utd_ratio, you need to set it to >1
    state_encoder_hidden_dim: int = 256
    latent_dim: int = 256
    target_entropy: float | None = None
    use_backup_entropy: bool = True
    grad_clip_norm: float = 40.0

    # Network configuration
    critic_network_kwargs: CriticNetworkConfig = field(default_factory=CriticNetworkConfig)
    actor_network_kwargs: ActorNetworkConfig = field(default_factory=ActorNetworkConfig)
    policy_kwargs: PolicyConfig = field(default_factory=PolicyConfig)

    actor_learner_config: ActorLearnerConfig = field(default_factory=ActorLearnerConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)

    def __post_init__(self):
        super().__post_init__()
        # Any validation specific to SAC configuration

    def get_optimizer_preset(self) -> MultiAdamConfig:
        return MultiAdamConfig(
            weight_decay=0.0,
            optimizer_groups={
                "actor": {"lr": self.actor_lr},
                "critic": {"lr": self.critic_lr},
                "temperature": {"lr": self.temperature_lr},
            },
        )

    def get_scheduler_preset(self) -> None:
        return None

    def validate_features(self) -> None:
        has_image = any(key.startswith("observation.image") for key in self.input_features)
        has_state = "observation.state" in self.input_features

        if not (has_state or has_image):
            raise ValueError(
                "You must provide either 'observation.state' or an image observation (key starting with 'observation.image') in the input features"
            )

        if "action" not in self.output_features:
            raise ValueError("You must provide 'action' in the output features")

    @property
    def image_features(self) -> list[str]:
        return [key for key in self.input_features if "image" in key]

    @property
    def observation_delta_indices(self) -> list:
        return None

    @property
    def action_delta_indices(self) -> list:
        return None  # SAC typically predicts one action at a time

    @property
    def reward_delta_indices(self) -> None:
        return None
