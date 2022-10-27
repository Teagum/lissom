"""
Self-organizing map base classes
"""
import pathlib
import pickle

import numpy as np
from scipy.spatial import distance

from . import defaults
from . import grid
from . import neighbors
from . import utilities as utils
from . typealias import Array, Metric, Shape, SomDims, WeightInit


class SomBase:
    def __init__(self, dims: SomDims, n_iter: int, eta: float,
                 nhr: float, nh_shape: str, init_weights: WeightInit,
                 metric: Metric, seed: float | None = None):

        self._grid = grid.SomGrid(dims[:2])
        self.n_features = dims[2]
        self._hit_counts = np.zeros(self.n_units)
        self.n_iter = n_iter
        self.metric = metric
        self._qrr = np.zeros(n_iter)
        self._trr = np.zeros(n_iter)
        self._weights: Array | None = None

        try:
            self._neighbourhood = getattr(neighbors, nh_shape)
        except AttributeError:
            raise AttributeError(f"Neighborhood shape {nh_shape} is unknown. "
                                 "Use one of `gaussian`, `mexican`, `rect`, or "
                                 "`star`")

        if 0 < eta <= 1.:
            self.init_eta = eta
        else:
            raise ValueError(f"Parameter ``eta``={self.init_eta} not in"
                             "range [0, 1]")

        if nhr >= 1:
            self.init_nhr = nhr
        else:
            raise ValueError("Neighbourhood radius must be int > 0.")

        if seed is not None:
            np.random.seed(seed)

        if isinstance(init_weights, str):
            self.init_weights = utils.weight_initializer[init_weights]
        elif callable(init_weights):
            self.init_weights = init_weights
        else:
            msg = f"Initializer must be string or callable."
            raise ValueError(msg)

        self._dists: Array | None = None

    @property
    def dims(self) -> SomDims:
        """Return the SOM dimensions."""
        return (*self._grid.shape, self.n_features)

    @property
    def dx(self) -> int:
        """Return the number of units along the first dimension."""
        return self._grid.shape[0]

    @property
    def dy(self) -> int:
        """Return the number of units along the second dimension."""
        return self._grid.shape[1]

    @property
    def dw(self) -> int:
        """Return the dimension of the weight vectors."""
        return self.n_features

    @property
    def n_units(self) -> int:
        """Return the total number of units on the SOM."""
        return self.dx * self.dy

    @property
    def shape(self) -> Shape:
        """Return the map shape."""
        return self._grid.shape

    @property
    def grid(self) -> Array:
        """Return the grid."""
        return self._grid

    @property
    def dists(self) -> Array:
        """Return the distance matrix of the grid points."""
        return self._dists

    @property
    def weights(self) -> Array:
        """Return the weight vectors."""
        return self._weights

    @property
    def hit_counts(self) -> Array:
        """Return total hit counts for each SOM unit."""
        return self._hit_counts

    @property
    def quantization_error(self) -> Array:
        """Return quantization error."""
        return self._qrr

    @property
    def topographic_error(self) -> Array:
        """Return topographic error."""
        return self._trr

    def calibrate(self, data: Array, target: Array) -> Array:
        """Retrieve the target value of the best matching input data vector
        for each unit weight vector.

        Args:
            data:     Input data set.
            target:  Target labels.

        Returns:
            Array of target values.
        """
        bm_dv, _ = utils.best_match(data, self._weights, self.metric)
        return target[bm_dv]

    def distribute(self, data: Array) -> dict[int, list[int]]:
        """Distribute the vectors of ``data`` on the SOM.

        Indices of vectors n ``data`` are mapped to the index of
        their best matching unit.

        Args:
            data:  Input data set.

        Returns:
            Dictionary with SOM unit indices as keys. Each key maps to a list
            that holds the indices of rows in ``data``, which best match this
            key.
        """
        return utils.distribute(self.match(data), self.n_units)

    def match_flat(self, data: Array) -> Array:
        """Return the index of the best matching unit for each vector in
        ``data``.

        Args:
            data:  Input data set.

        Returns:
            Array of SOM unit indices.
        """
        bmu, _ = utils.best_match(self._weights, data, self.metric)
        return bmu

    def match(self, data: Array) -> Array:
        """Return the multi index of the best matching unit for each vector in
        ``data``.

        Caution: This function returns the multi index into the array.

        Args:
            data:  Input data set.

        Returns:
            Array of SOM unit indices.
        """
        bmu = self.match_flat(data)
        return np.column_stack(np.unravel_index(bmu, self.shape))

    def predict(self, data: Array) -> Array:
        """Predict the SOM index of the best matching unit
        for each item in ``data``.

        Args:
            data:  Input data. Rows are items, columns are features.

        Returns:
            One-dimensional array of indices.
        """
        bmi, _ = utils.best_match(self.weights, data, self.metric)
        return bmi

    def save(self, path) -> None:
        """Save som object to file using pickle.

        Args:
            path: Save SOM to this path.
        """
        path = pathlib.Path(path)
        with path.open("wb") as file:
            pickle.dump(self, file)

    def save_weights(self, path) -> None:
        """Save weights only as a portable `.npy` file

        Args:
            path:  File path
        """
        np.save(path, self.weights, allow_pickle=False)

    def transform(self, data: Array) -> Array:
        """Transform each item in ``data`` to feature space.

        This, in principle, returns best matching unit's weight vectors.

        Args:
            data:  Input data. Rows are items, columns are features.

        Returns:
            Position of each data item in the feature space.
        """
        bmi = self.predict(data)
        return self.weights[bmi]


    def umatrix(self, radius: int = 1, scale: bool = True, norm: bool = True):
        """Compute U-matrix of SOM instance.

        Args:
            radius:   Map neighbourhood radius.
            scale:    If ``True``, scale each U-height by the number of the
                      associated unit's neighbours.
            norm:     Normalize U-matrix if ``True``.

        Returns:
            Unified distance matrix.
        """
        u_height = np.empty(self.n_units, dtype="float64")
        nhd_per_unit = self._grid.nhb_idx(self._grid.pos, radius)
        for i, nhd_idx in enumerate(nhd_per_unit):
            cwv = self._weights[[i]]
            nhd = self._weights[nhd_idx]
            u_height[i] = distance.cdist(cwv, nhd, self.metric).sum()
            if scale:
                u_height[i] /= len(nhd_idx)
        if norm:
            umax = u_height.max()
            if umax == 0:
                u_height = np.zeros_like(u_height)
            else:
                u_height /= u_height.max()
        return u_height.reshape(self.shape)


class BatchMap(SomBase):
    def __init__(self, dims: SomDims, n_iter: int, eta: float, nhr: float,
                 nh_shape: str = "gaussian", init_weights: WeightInit  = "rnd",
                 metric: Metric = "euclidean", seed: int = None):

        super().__init__(dims, n_iter, eta, nhr, nh_shape, init_weights, metric,
                         seed=seed)


class IncrementalMap(SomBase):
    def __init__(self, dims: SomDims, n_iter: int, eta: float, nhr: float,
                 nh_shape: str = "gaussian", init_weights: WeightInit = "rnd",
                 metric: Metric = "euclidean", seed: int = None):

        super().__init__(dims, n_iter, eta, nhr, nh_shape, init_weights, metric,
                         seed=seed)

    def fit(self, train_data, verbose=False, output_weights=False):
        self._weights = self.init_weights(self.dims, train_data)
        eta_ = utils.decrease_linear(self.init_eta, self.n_iter, defaults.final_eta)
        nhr_ = utils.decrease_expo(self.init_nhr, self.n_iter, defaults.final_nhr)

        np.random.seed(10)
        for (c_iter, c_eta, c_nhr) in zip(range(self.n_iter), eta_, nhr_):
            if verbose:
                print("iter: {:2} -- eta: {:<5} -- nh: {:<6}" \
                 .format(c_iter, np.round(c_eta, 4), np.round(c_nhr, 5)))

            for i, fvect in enumerate(np.random.permutation(train_data)):
                if output_weights:
                    fname = f"weights/weights_{c_iter:05}_{i:05}.npy"
                    with open(fname, "wb") as fobj:
                        np.save(fobj, self._weights, allow_pickle=False)
                bmu, err = utils.best_match(self.weights, fvect, self.metric)
                self._hit_counts[bmu] += 1
                m_idx = np.atleast_2d(np.unravel_index(bmu, self.shape)).T
                neighbors = self._neighbourhood(self._grid.pos, m_idx, c_nhr)
                self._weights += c_eta * neighbors * (fvect - self._weights)

            _, err = utils.best_match(self.weights, train_data, self.metric)
            self._qrr[c_iter] = err.sum() / train_data.shape[0]


class IncrementalKDTReeMap(SomBase):
    def __init__(self, dims: SomDims, n_iter: int, eta: float, nhr: float,
                 nh_shape: str = "star2", init_distr: str = "uniform",
                 metric: str = "euclidean", seed: int = None):

        super().__init__(dims, n_iter, eta, nhr, nh_shape, init_distr, metric,
                         seed=seed)

    def fit(self, train_data, verbose=False):
        """Fit SOM to input data."""
        self._weights = self.init_weights(train_data, self.shape)
        eta_ = utils.decrease_linear(self.init_eta, self.n_iter, defaults.final_eta)
        nhr_ = utils.decrease_expo(self.init_nhr, self.n_iter, defaults.final_nhr)
        iter_ = range(self.n_iter)

        np.random.seed(10)
        for (c_iter, c_eta, c_nhr) in zip(iter_, eta_, nhr_):
            if verbose:
                print("iter: {:2} -- eta: {:<5} -- nh: {:<6}" \
                 .format(c_iter, np.round(c_eta, 4), np.round(c_nhr, 5)))

            for fvect in np.random.permutation(train_data):
                bmu, _ = utils.best_match(self.weights, fvect, self.metric)
                self._hit_counts[bmu] += 1
                nh_idx = self._grid.nhb_idx(np.unravel_index(*bmu, self.shape), c_nhr)
                #dists = _distance.cdist(self._grid.pos[nh_idx], self._grid.pos[bmu])
                dists = np.ones(nh_idx.shape[0])
                kern = neighbors.gauss_kern(dists.ravel(), c_nhr) * c_eta
                self._weights[nh_idx] += ((fvect - self._weights[nh_idx]) * kern[:, None])

            _, err = asu.best_match(self.weights, train_data, self.metric)
            self._qrr[c_iter] = err.sum() / train_data.shape[0]
