import random
from functools import partial
from pathlib import Path
from typing import Protocol
from unittest.mock import patch

import datasets
import numpy as np
import pandas as pd
import PIL.Image
import pytest
import torch
from datasets import Dataset

from lerobot.common.datasets.lerobot_dataset import CODEBASE_VERSION, LeRobotDataset, LeRobotDatasetMetadata
from lerobot.common.datasets.utils import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DATA_PATH,
    DEFAULT_FEATURES,
    DEFAULT_FILE_SIZE_IN_MB,
    DEFAULT_VIDEO_PATH,
    flatten_dict,
    get_hf_features_from_features,
)
from tests.fixtures.constants import (
    DEFAULT_FPS,
    DUMMY_CAMERA_FEATURES,
    DUMMY_MOTOR_FEATURES,
    DUMMY_REPO_ID,
    DUMMY_ROBOT_TYPE,
    DUMMY_VIDEO_INFO,
)


class LeRobotDatasetFactory(Protocol):
    def __call__(self, *args, **kwargs) -> LeRobotDataset: ...


def get_task_index(tasks: datasets.Dataset, task: str) -> int:
    # TODO(rcadene): a bit complicated no? ^^
    task_idx = tasks.loc[task].task_index.item()
    return task_idx


@pytest.fixture(scope="session")
def img_tensor_factory():
    def _create_img_tensor(height=100, width=100, channels=3, dtype=torch.float32) -> torch.Tensor:
        return torch.rand((channels, height, width), dtype=dtype)

    return _create_img_tensor


@pytest.fixture(scope="session")
def img_array_factory():
    def _create_img_array(height=100, width=100, channels=3, dtype=np.uint8) -> np.ndarray:
        if np.issubdtype(dtype, np.unsignedinteger):
            # Int array in [0, 255] range
            img_array = np.random.randint(0, 256, size=(height, width, channels), dtype=dtype)
        elif np.issubdtype(dtype, np.floating):
            # Float array in [0, 1] range
            img_array = np.random.rand(height, width, channels).astype(dtype)
        else:
            raise ValueError(dtype)
        return img_array

    return _create_img_array


@pytest.fixture(scope="session")
def img_factory(img_array_factory):
    def _create_img(height=100, width=100) -> PIL.Image.Image:
        img_array = img_array_factory(height=height, width=width)
        return PIL.Image.fromarray(img_array)

    return _create_img


@pytest.fixture(scope="session")
def features_factory():
    def _create_features(
        motor_features: dict = DUMMY_MOTOR_FEATURES,
        camera_features: dict = DUMMY_CAMERA_FEATURES,
        use_videos: bool = True,
    ) -> dict:
        if use_videos:
            camera_ft = {
                key: {"dtype": "video", **ft, **DUMMY_VIDEO_INFO} for key, ft in camera_features.items()
            }
        else:
            camera_ft = {key: {"dtype": "image", **ft} for key, ft in camera_features.items()}
        return {
            **motor_features,
            **camera_ft,
            **DEFAULT_FEATURES,
        }

    return _create_features


@pytest.fixture(scope="session")
def info_factory(features_factory):
    def _create_info(
        codebase_version: str = CODEBASE_VERSION,
        fps: int = DEFAULT_FPS,
        robot_type: str = DUMMY_ROBOT_TYPE,
        total_episodes: int = 0,
        total_frames: int = 0,
        total_tasks: int = 0,
        total_videos: int = 0,
        chunks_size: int = DEFAULT_CHUNK_SIZE,
        files_size_in_mb: float = DEFAULT_FILE_SIZE_IN_MB,
        data_path: str = DEFAULT_DATA_PATH,
        video_path: str = DEFAULT_VIDEO_PATH,
        motor_features: dict = DUMMY_MOTOR_FEATURES,
        camera_features: dict = DUMMY_CAMERA_FEATURES,
        use_videos: bool = True,
    ) -> dict:
        features = features_factory(motor_features, camera_features, use_videos)
        return {
            "codebase_version": codebase_version,
            "robot_type": robot_type,
            "total_episodes": total_episodes,
            "total_frames": total_frames,
            "total_tasks": total_tasks,
            "total_videos": total_videos,
            "chunks_size": chunks_size,
            "files_size_in_mb": files_size_in_mb,
            "fps": fps,
            "splits": {},
            "data_path": data_path,
            "video_path": video_path if use_videos else None,
            "features": features,
        }

    return _create_info


@pytest.fixture(scope="session")
def stats_factory():
    def _create_stats(
        features: dict[str] | None = None,
    ) -> dict:
        stats = {}
        for key, ft in features.items():
            shape = ft["shape"]
            dtype = ft["dtype"]
            if dtype in ["image", "video"]:
                stats[key] = {
                    "max": np.full((3, 1, 1), 1, dtype=np.float32).tolist(),
                    "mean": np.full((3, 1, 1), 0.5, dtype=np.float32).tolist(),
                    "min": np.full((3, 1, 1), 0, dtype=np.float32).tolist(),
                    "std": np.full((3, 1, 1), 0.25, dtype=np.float32).tolist(),
                    "count": [10],
                }
            else:
                stats[key] = {
                    "max": np.full(shape, 1, dtype=dtype).tolist(),
                    "mean": np.full(shape, 0.5, dtype=dtype).tolist(),
                    "min": np.full(shape, 0, dtype=dtype).tolist(),
                    "std": np.full(shape, 0.25, dtype=dtype).tolist(),
                    "count": [10],
                }
        return stats

    return _create_stats


# @pytest.fixture(scope="session")
# def episodes_stats_factory(stats_factory):
#     def _create_episodes_stats(
#         features: dict[str],
#         total_episodes: int = 3,
#     ) -> dict:

#         def _generator(total_episodes):
#             for ep_idx in range(total_episodes):
#                 flat_ep_stats = flatten_dict(stats_factory(features))
#                 flat_ep_stats["episode_index"] = ep_idx
#                 yield flat_ep_stats

#         # Simpler to rely on generator instead of from_dict
#         return Dataset.from_generator(lambda: _generator(total_episodes))

#     return _create_episodes_stats


@pytest.fixture(scope="session")
def tasks_factory():
    def _create_tasks(total_tasks: int = 3) -> pd.DataFrame:
        ids = list(range(total_tasks))
        tasks = [f"Perform action {i}." for i in ids]
        df = pd.DataFrame({"task_index": ids}, index=tasks)
        return df

    return _create_tasks


@pytest.fixture(scope="session")
def episodes_factory(tasks_factory, stats_factory):
    def _create_episodes(
        features: dict[str],
        total_episodes: int = 3,
        total_frames: int = 400,
        video_keys: list[str] | None = None,
        tasks: pd.DataFrame | None = None,
        multi_task: bool = False,
    ):
        if total_episodes <= 0 or total_frames <= 0:
            raise ValueError("num_episodes and total_length must be positive integers.")
        if total_frames < total_episodes:
            raise ValueError("total_length must be greater than or equal to num_episodes.")

        if tasks is None:
            min_tasks = 2 if multi_task else 1
            total_tasks = random.randint(min_tasks, total_episodes)
            tasks = tasks_factory(total_tasks)

        num_tasks_available = len(tasks)

        if total_episodes < num_tasks_available and not multi_task:
            raise ValueError("The number of tasks should be less than the number of episodes.")

        # Generate random lengths that sum up to total_length
        lengths = np.random.multinomial(total_frames, [1 / total_episodes] * total_episodes).tolist()

        # Create empty dictionaries with all keys
        d = {
            "episode_index": [],
            "meta/episodes/chunk_index": [],
            "meta/episodes/file_index": [],
            "data/chunk_index": [],
            "data/file_index": [],
            "tasks": [],
            "length": [],
        }
        if video_keys is not None:
            for video_key in video_keys:
                d[f"videos/{video_key}/chunk_index"] = []
                d[f"videos/{video_key}/file_index"] = []

        for stats_key in flatten_dict({"stats": stats_factory(features)}):
            d[stats_key] = []

        remaining_tasks = list(tasks.index)
        for ep_idx in range(total_episodes):
            num_tasks_in_episode = random.randint(1, min(3, num_tasks_available)) if multi_task else 1
            tasks_to_sample = remaining_tasks if len(remaining_tasks) > 0 else list(tasks.index)
            episode_tasks = random.sample(tasks_to_sample, min(num_tasks_in_episode, len(tasks_to_sample)))
            if remaining_tasks:
                for task in episode_tasks:
                    remaining_tasks.remove(task)

            d["episode_index"].append(ep_idx)
            # TODO(rcadene): remove heuristic of only one file
            d["meta/episodes/chunk_index"].append(0)
            d["meta/episodes/file_index"].append(0)
            d["data/chunk_index"].append(0)
            d["data/file_index"].append(0)
            d["tasks"].append(episode_tasks)
            d["length"].append(lengths[ep_idx])

            if video_keys is not None:
                for video_key in video_keys:
                    d[f"videos/{video_key}/chunk_index"].append(0)
                    d[f"videos/{video_key}/file_index"].append(0)

            # Add stats columns like "stats/action/max"
            for stats_key, stats in flatten_dict({"stats": stats_factory(features)}).items():
                d[stats_key].append(stats)

        return Dataset.from_dict(d)

    return _create_episodes


@pytest.fixture(scope="session")
def hf_dataset_factory(features_factory, tasks_factory, episodes_factory, img_array_factory):
    def _create_hf_dataset(
        features: dict | None = None,
        tasks: pd.DataFrame | None = None,
        episodes: datasets.Dataset | None = None,
        fps: int = DEFAULT_FPS,
    ) -> datasets.Dataset:
        if tasks is None:
            tasks = tasks_factory()
        if episodes is None:
            episodes = episodes_factory()
        if features is None:
            features = features_factory()

        timestamp_col = np.array([], dtype=np.float32)
        frame_index_col = np.array([], dtype=np.int64)
        episode_index_col = np.array([], dtype=np.int64)
        task_index = np.array([], dtype=np.int64)
        for ep_dict in episodes:
            timestamp_col = np.concatenate((timestamp_col, np.arange(ep_dict["length"]) / fps))
            frame_index_col = np.concatenate((frame_index_col, np.arange(ep_dict["length"], dtype=int)))
            episode_index_col = np.concatenate(
                (episode_index_col, np.full(ep_dict["length"], ep_dict["episode_index"], dtype=int))
            )
            # Slightly incorrect, but for simplicity, we assign to all frames the first task defined in the episode metadata.
            # TODO(rcadene): assign the tasks of the episode per chunks of frames
            ep_task_index = get_task_index(tasks, ep_dict["tasks"][0])
            task_index = np.concatenate((task_index, np.full(ep_dict["length"], ep_task_index, dtype=int)))

        index_col = np.arange(len(episode_index_col))

        robot_cols = {}
        for key, ft in features.items():
            if ft["dtype"] == "image":
                robot_cols[key] = [
                    img_array_factory(height=ft["shapes"][1], width=ft["shapes"][0])
                    for _ in range(len(index_col))
                ]
            elif ft["shape"][0] > 1 and ft["dtype"] != "video":
                robot_cols[key] = np.random.random((len(index_col), ft["shape"][0])).astype(ft["dtype"])

        hf_features = get_hf_features_from_features(features)
        dataset = datasets.Dataset.from_dict(
            {
                **robot_cols,
                "timestamp": timestamp_col,
                "frame_index": frame_index_col,
                "episode_index": episode_index_col,
                "index": index_col,
                "task_index": task_index,
            },
            features=hf_features,
        )
        dataset.set_format("torch")
        return dataset

    return _create_hf_dataset


@pytest.fixture(scope="session")
def lerobot_dataset_metadata_factory(
    info_factory,
    stats_factory,
    tasks_factory,
    episodes_factory,
    mock_snapshot_download_factory,
):
    def _create_lerobot_dataset_metadata(
        root: Path,
        repo_id: str = DUMMY_REPO_ID,
        info: dict | None = None,
        stats: dict | None = None,
        tasks: pd.DataFrame | None = None,
        episodes: datasets.Dataset | None = None,
    ) -> LeRobotDatasetMetadata:
        if info is None:
            info = info_factory()
        if stats is None:
            stats = stats_factory(features=info["features"])
        if tasks is None:
            tasks = tasks_factory(total_tasks=info["total_tasks"])
        if episodes is None:
            video_keys = [key for key, ft in info["features"].items() if ft["dtype"] == "video"]
            episodes = episodes_factory(
                features=info["features"],
                total_episodes=info["total_episodes"],
                total_frames=info["total_frames"],
                video_keys=video_keys,
                tasks=tasks,
            )

        mock_snapshot_download = mock_snapshot_download_factory(
            info=info,
            stats=stats,
            tasks=tasks,
            episodes=episodes,
        )
        with (
            patch("lerobot.common.datasets.lerobot_dataset.get_safe_version") as mock_get_safe_version_patch,
            patch(
                "lerobot.common.datasets.lerobot_dataset.snapshot_download"
            ) as mock_snapshot_download_patch,
        ):
            mock_get_safe_version_patch.side_effect = lambda repo_id, version: version
            mock_snapshot_download_patch.side_effect = mock_snapshot_download

            return LeRobotDatasetMetadata(repo_id=repo_id, root=root)

    return _create_lerobot_dataset_metadata


@pytest.fixture(scope="session")
def lerobot_dataset_factory(
    info_factory,
    stats_factory,
    tasks_factory,
    episodes_factory,
    hf_dataset_factory,
    mock_snapshot_download_factory,
    lerobot_dataset_metadata_factory,
) -> LeRobotDatasetFactory:
    def _create_lerobot_dataset(
        root: Path,
        repo_id: str = DUMMY_REPO_ID,
        total_episodes: int = 3,
        total_frames: int = 150,
        total_tasks: int = 1,
        multi_task: bool = False,
        info: dict | None = None,
        stats: dict | None = None,
        tasks: pd.DataFrame | None = None,
        episodes_metadata: datasets.Dataset | None = None,
        hf_dataset: datasets.Dataset | None = None,
        **kwargs,
    ) -> LeRobotDataset:
        if info is None:
            info = info_factory(
                total_episodes=total_episodes, total_frames=total_frames, total_tasks=total_tasks
            )
        if stats is None:
            stats = stats_factory(features=info["features"])
        if tasks is None:
            tasks = tasks_factory(total_tasks=info["total_tasks"])
        if episodes_metadata is None:
            video_keys = [key for key, ft in info["features"].items() if ft["dtype"] == "video"]
            episodes_metadata = episodes_factory(
                features=info["features"],
                total_episodes=info["total_episodes"],
                total_frames=info["total_frames"],
                video_keys=video_keys,
                tasks=tasks,
                multi_task=multi_task,
            )
        if not hf_dataset:
            hf_dataset = hf_dataset_factory(tasks=tasks, episodes=episodes_metadata, fps=info["fps"])

        mock_snapshot_download = mock_snapshot_download_factory(
            info=info,
            stats=stats,
            tasks=tasks,
            episodes=episodes_metadata,
            hf_dataset=hf_dataset,
        )
        mock_metadata = lerobot_dataset_metadata_factory(
            root=root,
            repo_id=repo_id,
            info=info,
            stats=stats,
            tasks=tasks,
            episodes=episodes_metadata,
        )
        with (
            patch("lerobot.common.datasets.lerobot_dataset.LeRobotDatasetMetadata") as mock_metadata_patch,
            patch("lerobot.common.datasets.lerobot_dataset.get_safe_version") as mock_get_safe_version_patch,
            patch(
                "lerobot.common.datasets.lerobot_dataset.snapshot_download"
            ) as mock_snapshot_download_patch,
        ):
            mock_metadata_patch.return_value = mock_metadata
            mock_get_safe_version_patch.side_effect = lambda repo_id, version: version
            mock_snapshot_download_patch.side_effect = mock_snapshot_download

            return LeRobotDataset(repo_id=repo_id, root=root, **kwargs)

    return _create_lerobot_dataset


@pytest.fixture(scope="session")
def empty_lerobot_dataset_factory() -> LeRobotDatasetFactory:
    return partial(LeRobotDataset.create, repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS)
