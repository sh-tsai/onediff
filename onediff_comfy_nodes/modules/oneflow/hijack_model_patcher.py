
from comfy.model_patcher import ModelPatcher

from ..sd_hijack_utils import Hijacker
from .patch_management import PatchType, create_patch_executor
from .utils.booster_utils import is_using_oneflow_backend

def clone_oneflow(org_fn, self, *args, **kwargs):    
    n = org_fn(self, *args, **kwargs)
    create_patch_executor(PatchType.UiNodeWithIndexPatch).copy_to(self, n)
    dc_patch_executor = create_patch_executor(PatchType.DCUNetExecutorPatch)
    if dc_patch_executor.check_patch(self):
        dc_patch_executor.copy_to(self, n)
    return n

def cond_func(org_fn, self):
    return is_using_oneflow_backend(self)
    
model_patch_hijacker = Hijacker()

model_patch_hijacker.register(ModelPatcher.clone, clone_oneflow, cond_func)

