# Copyright (c) 2012, GPy authors (see AUTHORS.txt).
# Licensed under the BSD 3-clause license (see LICENSE.txt)


import numpy as np
from paramz.caching import Cache_this
from scipy.spatial.distance import cdist

from .stationary import Stationary
from .psi_comp import PSICOMP_RBF, PSICOMP_RBF_GPU
from ...core import Param
from paramz.transformations import Logexp
from .grid_kerns import GridRBF


class RBF(Stationary):
    """
    Radial Basis Function kernel, aka squared-exponential, exponentiated quadratic or Gaussian kernel:

    .. math::

       k(r) = \sigma^2 \exp \\bigg(- \\frac{1}{2} r^2 \\bigg)

    """
    _support_GPU = True

    def __init__(self, input_dim, variance=1., lengthscale=None, ARD=False, active_dims=None, name='rbf', useGPU=False,
                 inv_l=False):
        super(RBF, self).__init__(input_dim, variance, lengthscale, ARD, active_dims, name, useGPU=useGPU)
        if self.useGPU:
            self.psicomp = PSICOMP_RBF_GPU()
        else:
            self.psicomp = PSICOMP_RBF()
        self.use_invLengthscale = inv_l
        if inv_l:
            self.unlink_parameter(self.lengthscale)
            self.inv_l = Param('inv_lengthscale', 1. / self.lengthscale ** 2, Logexp())
            self.link_parameter(self.inv_l)

    def to_dict(self):
        """
        Convert the object into a json serializable dictionary.

        Note: It uses the private method _save_to_input_dict of the parent.

        :return dict: json serializable dictionary containing the needed information to instantiate the object
        """

        input_dict = super(RBF, self)._save_to_input_dict()
        input_dict["class"] = "GPy.kern.RBF"
        input_dict["inv_l"] = self.use_invLengthscale
        if input_dict["inv_l"] == True:
            input_dict["lengthscale"] = np.sqrt(1 / float(self.inv_l))
        return input_dict

    def K_of_r(self, r):
        return self.variance * np.exp(-0.5 * r ** 2)

    def dK_dr(self, r):
        return -r * self.K_of_r(r)

    def dK2_drdr(self, r):
        return (r ** 2 - 1) * self.K_of_r(r)

    def dK2_drdr_diag(self):
        return -self.variance  # as the diagonal of r is always filled with zeros

    def __getstate__(self):
        dc = super(RBF, self).__getstate__()
        if self.useGPU:
            dc['psicomp'] = PSICOMP_RBF()
            dc['useGPU'] = False
        return dc

    def __setstate__(self, state):
        self.use_invLengthscale = False
        return super(RBF, self).__setstate__(state)

    def spectrum(self, omega):
        assert self.input_dim == 1  # TODO: higher dim spectra?
        return self.variance * np.sqrt(2 * np.pi) * self.lengthscale * np.exp(-self.lengthscale * 2 * omega ** 2 / 2)

    def parameters_changed(self):
        if self.use_invLengthscale: self.lengthscale[:] = 1. / np.sqrt(self.inv_l + 1e-200)
        super(RBF, self).parameters_changed()

    def get_one_dimensional_kernel(self, dim):
        """
        Specially intended for Grid regression.
        """
        oneDkernel = GridRBF(input_dim=1, variance=self.variance.copy(), originalDimensions=dim)
        return oneDkernel

    # ---------------------------------------#
    #             PSI statistics            #
    # ---------------------------------------#

    def psi0(self, Z, variational_posterior):
        return self.psicomp.psicomputations(self, Z, variational_posterior)[0]

    def psi1(self, Z, variational_posterior):
        return self.psicomp.psicomputations(self, Z, variational_posterior)[1]

    def psi2(self, Z, variational_posterior):
        return self.psicomp.psicomputations(self, Z, variational_posterior, return_psi2_n=False)[2]

    def psi2n(self, Z, variational_posterior):
        return self.psicomp.psicomputations(self, Z, variational_posterior, return_psi2_n=True)[2]

    def update_gradients_expectations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z, variational_posterior):
        dL_dvar, dL_dlengscale = self.psicomp.psiDerivativecomputations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z,
                                                                        variational_posterior)[:2]
        self.variance.gradient = dL_dvar
        self.lengthscale.gradient = dL_dlengscale
        if self.use_invLengthscale:
            self.inv_l.gradient = dL_dlengscale * (self.lengthscale ** 3 / -2.)

    def gradients_Z_expectations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z, variational_posterior):
        return self.psicomp.psiDerivativecomputations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z, variational_posterior)[2]

    def gradients_qX_expectations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z, variational_posterior):
        return self.psicomp.psiDerivativecomputations(self, dL_dpsi0, dL_dpsi1, dL_dpsi2, Z, variational_posterior)[3:]

    def update_gradients_diag(self, dL_dKdiag, X):
        super(RBF, self).update_gradients_diag(dL_dKdiag, X)
        if self.use_invLengthscale: self.inv_l.gradient = self.lengthscale.gradient * (self.lengthscale ** 3 / -2.)

    def update_gradients_full(self, dL_dK, X, X2=None):
        super(RBF, self).update_gradients_full(dL_dK, X, X2)
        if self.use_invLengthscale: self.inv_l.gradient = self.lengthscale.gradient * (self.lengthscale ** 3 / -2.)


class RBFKernelKernel(RBF):
    """Kernel kernel"""

    _support_GPU = True

    def __init__(self, distance_metric, dm_kwargs_dict=None, input_dim=1, variance=1., lengthscale=None, ARD=False,
                 active_dims=None, name='kernel_kernel', useGPU=False, inv_l=False):
        super(RBFKernelKernel, self).__init__(input_dim, variance, lengthscale, ARD, active_dims, name, useGPU=useGPU,
                                              inv_l=inv_l)
        self.dist_metric = distance_metric
        if dm_kwargs_dict is None:
            self.dm_kwargs_dict = dict()
        else:
            self.dm_kwargs_dict = dm_kwargs_dict

    ### overrride this

    def _unscaled_dist(self, X, X2=None):
        """
        Compute the Euclidean distance between each row of X and X2, or between
        each pair of rows of X if X2 is None.
        """
        if X2 is None:
            X2 = X
        r = cdist(X, X2, self.dist_metric, **self.dm_kwargs_dict)
        return r

    ### overrride this
    @Cache_this(limit=3, ignore_args=())
    def _scaled_dist(self, X, X2=None):
        """
        Efficiently compute the scaled distance, r.

        ..math::
            r = \sqrt( \sum_{q=1}^Q (x_q - x'q)^2/l_q^2 )

        Note that if thre is only one lengthscale, l comes outside the sum. In
        this case we compute the unscaled distance first (in a separate
        function for caching) and divide by lengthscale afterwards

        """
        if self.ARD:
            # FIXME: currently ARD has no effect because input dim always = 1
            #             if X2 is not None:
            #                 X2 = X2 / self.lengthscale
            #             return self._unscaled_dist(X/self.lengthscale, X2)
            return self._unscaled_dist(X, X2) / self.lengthscale
        else:
            return self._unscaled_dist(X, X2) / self.lengthscale

    ###

    def to_dict(self):
        """
        Convert the object into a json serializable dictionary.

        Note: It uses the private method _save_to_input_dict of the parent.

        :return dict: json serializable dictionary containing the needed information to instantiate the object
        """

        input_dict = super(RBFKernelKernel, self)._save_to_input_dict()
        input_dict["class"] = "GPy.kern.RBFKernelKernel"
        input_dict["inv_l"] = self.use_invLengthscale
        if input_dict["inv_l"]:
            input_dict["lengthscale"] = np.sqrt(1 / float(self.inv_l))
        return input_dict


class RBFDistanceBuilderKernelKernel(RBF):
    """RBF distance builder kernel kernel"""

    _support_GPU = True

    def __init__(self, distance_builder, n_models=0, input_dim=1, variance=1., lengthscale=None, ARD=False,
                 active_dims=None, name='rbf_db_kernel_kernel', useGPU=False, inv_l=False):
        super(RBFDistanceBuilderKernelKernel, self).__init__(input_dim, variance, lengthscale, ARD, active_dims, name,
                                                             useGPU=useGPU, inv_l=inv_l)
        assert input_dim == 1
        self.distance_builder = distance_builder
        self.n_models = n_models

    ### overrride this

    def _unscaled_dist(self, X, X2=None):
        """
        Compute the Euclidean distance between each row of X and X2, or between
        each pair of rows of X if X2 is None.
        """
        if X2 is None:
            X2 = X
        r = self.distance_builder.get_kernel(self.n_models)
        assert r.ndim == 2 and r.shape[0] == r.shape[1]
        r = r[X.flatten().astype(np.int)][:, X2.flatten().astype(np.int)]
        return r

    ### overrride this
    @Cache_this(limit=3, ignore_args=())
    def _scaled_dist(self, X, X2=None):
        """
        Efficiently compute the scaled distance, r.

        ..math::
            r = \sqrt( \sum_{q=1}^Q (x_q - x'q)^2/l_q^2 )

        Note that if thre is only one lengthscale, l comes outside the sum. In
        this case we compute the unscaled distance first (in a separate
        function for caching) and divide by lengthscale afterwards

        """
        if self.ARD:
            # FIXME: currently ARD has no effect because input dim always = 1
            #             if X2 is not None:
            #                 X2 = X2 / self.lengthscale
            #             return self._unscaled_dist(X/self.lengthscale, X2)
            return self._unscaled_dist(X, X2) / self.lengthscale
        else:
            return self._unscaled_dist(X, X2) / self.lengthscale

    ###

    def to_dict(self):
        """
        Convert the object into a json serializable dictionary.

        Note: It uses the private method _save_to_input_dict of the parent.

        :return dict: json serializable dictionary containing the needed information to instantiate the object
        """

        input_dict = super(RBFDistanceBuilderKernelKernel, self)._save_to_input_dict()
        input_dict["class"] = "GPy.kern.RBFDistanceBuilderKernelKernel"
        input_dict["inv_l"] = self.use_invLengthscale
        if input_dict["inv_l"]:
            input_dict["lengthscale"] = np.sqrt(1 / float(self.inv_l))
        return input_dict