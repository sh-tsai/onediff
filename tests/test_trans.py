from typing import Tuple, Dict, Any
import torch
from torch.fx.node import Argument

class NegSigmSwapXformer(torch.fx.Transformer):
    def call_function(self, target : 'Target', args : Tuple[Argument, ...], kwargs : Dict[str, Any]) -> Any:
        if target == torch.sigmoid:
            return torch.neg(*args, **kwargs)
        return super().call_function(n)

    def call_method(self, target : 'Target', args : Tuple[Argument, ...], kwargs : Dict[str, Any]) -> Any:
        if target == 'neg':
            call_self, *args_tail = args
            return call_self.sigmoid(*args_tail, **kwargs)
        return super().call_method(n)

def fn(x):
    return torch.sigmoid(x).neg()

gm = torch.fx.symbolic_trace(fn)
print(gm)

transformed : torch.nn.Module = NegSigmSwapXformer(gm).transform()
print(transformed)

input = torch.randn(3, 4)
torch.testing.assert_close(transformed(input), torch.neg(input).sigmoid())