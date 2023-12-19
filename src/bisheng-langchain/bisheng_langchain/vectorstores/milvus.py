from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple, Callable
from langchain.vectorstores import Milvus as MilvusOrigin


class Milvus(MilvusOrigin):

    @staticmethod
    def _relevance_score_fn(distance: float) -> float:
        """Normalize the distance to a score on a scale [0, 1]."""
        # Todo: normalize the es score on a scale [0, 1]
        return 1 - distance

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        return self._relevance_score_fn