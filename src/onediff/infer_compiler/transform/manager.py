import importlib
import os
import types
import warnings
import logging
from typing import Dict, List, Union
from pathlib import Path
from ..utils.log_utils import logger
from ..import_tools.importer import LazyMocker

__all__ = ["transform_mgr"]


class TransformManager:
    """TransformManager

    __init__ args:
        `debug_mode`: Whether to print debug info.
        `tmp_dir`: The temp dir to store mock files.
    """

    def __init__(self, debug_mode=False, tmp_dir="./output"):
        self.debug_mode = debug_mode
        self._torch_to_oflow_cls_map = {}
        self._oflow_to_torch_cls_map = {}
        self._setup_logger()
        self.mocker = LazyMocker(prefix="", suffix="", tmp_dir=None)

    def _setup_logger(self):
        name = "ONEDIFF"
        level = logging.DEBUG if self.debug_mode else logging.WARNING
        logger.configure_logging(name=name, file_name=None, level=level, log_dir=None)
        self.logger = logger

    def get_mocked_packages(self):
        return self.mocker.mocked_packages

    def load_class_proxies_from_packages(self, package_names: List[Union[Path, str]]):
        self.logger.debug(f"Loading modules: {package_names}")
        for package_name in package_names:
            self.mocker.mock_package(package_name)
            self.logger.info(f"Loaded Mock Torch Package: {package_name} successfully")

    def update_class_proxies(self, class_proxy_dict: Dict[str, type], verbose=True):
        """Update `_torch_to_oflow_cls_map` with `class_proxy_dict`.

        example:
            `class_proxy_dict = {"mock_torch.nn.Conv2d": flow.nn.Conv2d}`

        """
        self._torch_to_oflow_cls_map.update(class_proxy_dict)

        debug_message = f"Updated class proxies: {len(class_proxy_dict)=}"
        debug_message += f"\n{class_proxy_dict}\n"
        self.logger.debug(debug_message)

    def _transform_entity(self, entity):
        # TODO: Optimize _transform_entity for faster SDXL conversion (1.47s)
        result = self.mocker.mock_entity(entity)
        if result is None:
            RuntimeError(f"Failed to transform entity: {entity}")
        return result

    def get_transformed_entity_name(self, entity):
        return self.mocker.get_mock_entity_name(entity)

    def transform_cls(self, cls):
        """Transform a class to a mock class ."""
        full_cls_name = cls.__module__ + "." + cls.__qualname__
        mock_full_cls_name = self.get_transformed_entity_name(full_cls_name)

        # transform cache
        if mock_full_cls_name in self._torch_to_oflow_cls_map:
            return self._torch_to_oflow_cls_map[mock_full_cls_name]

        # transform
        if cls.__module__.startswith("torch."):
            mod_name = cls.__module__.replace("torch.", "oneflow.")
            mod = importlib.import_module(mod_name)
            mock_cls = getattr(mod, cls.__name__)
        else:
            mock_cls = self._transform_entity(mock_full_cls_name)

        self._torch_to_oflow_cls_map[mock_full_cls_name] = mock_cls
        self._oflow_to_torch_cls_map[mock_full_cls_name] = cls
        return mock_cls

    def reverse_transform_cls(self, cls):
        full_cls_name = cls.__module__ + "." + cls.__qualname__
        mock_full_cls_name = self.get_transformed_entity_name(full_cls_name)
        if mock_full_cls_name in self._oflow_to_torch_cls_map:
            return self._oflow_to_torch_cls_map[mock_full_cls_name]
        else:
            self.logger.info(
                f"{mock_full_cls_name} not in _oflow_to_torch_cls_map, import it directly."
            )
            mod = importlib.import_module(cls.__module__)
            return getattr(mod, cls.__qualname__)

    def transform_func(self, func: types.FunctionType):
        # TODO: support transform function cache
        return self._transform_entity(func)

    def transform_package(self, package_name):
        return self._transform_entity(package_name)


debug_mode = os.getenv("ONEDIFF_DEBUG", "0") == "1"
transform_mgr = TransformManager(debug_mode=debug_mode, tmp_dir=None)

if not transform_mgr.debug_mode:
    warnings.simplefilter("ignore", category=UserWarning)
    warnings.simplefilter("ignore", category=FutureWarning)


if importlib.util.find_spec("pydantic") is not None:
    import pydantic
    if pydantic.VERSION < "2.5.2":
        logger.warning(
            f"Pydantic version {pydantic.VERSION} is too low, please upgrade to 2.5.2 or higher."
        )
        from oneflow.mock_torch.mock_utils import MockEnableDisableMixin

        MockEnableDisableMixin.hazard_list.append(
            "huggingface_hub.inference._text_generation"
        )


