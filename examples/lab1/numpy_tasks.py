"""Заготовки задач на NumPy."""

import numpy as np
from grader_contracts.numpy_tasks import BinarizeInput, MatrixVectorBatchInput


def sum_prod(data: MatrixVectorBatchInput) -> np.ndarray:
    matrices, vectors = data.matrices, data.vectors
    raise NotImplementedError  # TODO


def binarize(data: BinarizeInput) -> np.ndarray:
    matrix, threshold = data.matrix, data.threshold
    raise NotImplementedError  # TODO
