import os
from glob import glob

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import binned_statistic

from astropy.io import fits
from astropy.time import Time
from astropy.stats import SigmaClip, mad_std

from .linalg import linreg, RegressionResult

__all__ = ['CheopsLightCurve', 'JointLightCurve']

attrs = [  # These vectors are from DRP
    "background",
    "bjd_time",
    "centroid_x",
    "centroid_y",
    "conta_lc",
    "conta_lc_err",
    "dark",
    "event",
    "flux",
    "fluxerr",
    "location_x",
    "location_y",
    "mjd_time",
    "roll_angle",
    "smearing_lc",
    "smearing_lc_err",
    "status",
    "utc_time"
] + [  # These vectors are from PIPE
    "u0",
    "u1",
    "u2",
    "xc",
    "yc",
    "bg"
]


def normalize(vector):
    """
    Normalize a vector such that its contents range from [-0.5, 0.5]
    """
    return (vector - vector.min()) / vector.ptp() - 0.5


class CheopsLightCurve(object):
    """
    Data handling class for CHEOPS light curves.
    """

    def __init__(self, record_array={}, extra_basis_vectors=None,
                 time=None, mask=None, norm=True):
        """
        Parameters
        ----------
        record_array : `~numpy.recarray`
            Record array of column vectors and their labels (names). Often
            this record array comes straight from a FITS file.
        hk_record_array : `~numpy.recarray`
            Record array of column vectors and their labels from the housekeeping
            FITS file which often ends in "SCI_CAL_SubArray_*.fits". Often
            this record array comes straight from a FITS file.
        norm : bool
            Normalize the fluxes such that the median flux is unity. Default is
            True.
        """
        self.recs = record_array
        self.extra_basis_vectors = extra_basis_vectors

        for key in attrs:
            if (hasattr(self.recs, 'columns') and
                    key in [i.lower() for i in self.recs.names]):
                setattr(self, key, self.recs[key.upper()])

            # Catch case for renamed roll angle key in the PIPE outputs
            elif (hasattr(self.recs, 'columns') and
                    'roll' in [i.lower() for i in self.recs.names]):
                setattr(self, 'roll_angle', self.recs['roll'])

        self.time = (Time(self.bjd_time, format='jd')
                     if hasattr(self, 'bjd_time') else time)

        if hasattr(self, 'status') and hasattr(self, 'event'):
            self.mask = (np.isnan(self.flux) | self.status.astype(bool) |
                         self.event.astype(bool)) if hasattr(self, 'flux') else mask
        else:
            self.mask = np.isnan(self.flux) if hasattr(self, 'flux') else mask

        if hasattr(self, 'flux') and norm:
            self.fluxerr = self.fluxerr / np.nanmedian(self.flux)
            self.flux = self.flux / np.nanmedian(self.flux)

    @classmethod
    def from_fits(cls, path, extra_basis_vectors=None, norm=True):
        """
        Load a FITS file from DACE or the DRP.

        Parameters
        ----------
        path : str
            Path to the FITS file containing the data to load.
        extra_basis_vectors : `~numpy.ndarray`
            Extra basis vectors to add to the design matrix.
        norm : bool
            Normalize the fluxes such that the median flux is unity. Default is
            True.
        """
        return cls(fits.getdata(path), extra_basis_vectors=extra_basis_vectors,
                   norm=norm)

    @classmethod
    def from_example(cls, norm=True):
        """
        Load example 55 Cnc e light curve (**NOTE**: this is not real data).

        Parameters
        ----------
        norm : bool
            Normalize the fluxes such that the median flux is unity. Default is
            True.
        """
        path = os.path.join(os.path.dirname(__file__), 'data',
                            'example_55Cnce.fits')
        return cls.from_fits(path, norm=norm)

    def plot(self, ax=None, **kwargs):
        """
        Plot the light curve.

        Parameters
        ----------
        ax : `~matplotlib.axes.Axes`
            Matplotlib axis instance on which to build the plot
        kwargs : dict
            Further keyword arguments to pass to `~matplotlib.pyplot.plot`.

        Returns
        -------
        ax : `~matplotlib.axes.Axes`
            Matplotlib axis instance with the light curve plotted on it.
        """
        if ax is None:
            ax = plt.gca()

        ax.errorbar(self.bjd_time[~self.mask], self.flux[~self.mask],
                    self.fluxerr[~self.mask], **kwargs)

        return ax

    def design_matrix(self, norm=True):
        """
        Generate the design matrix.

        Parameters
        ----------
        norm : bool
            Normalize the column vectors within the design matrix such that they
            have mean=zero and range=unity.

        Returns
        -------
        X : `~numpy.ndarray`
            Design matrix (concatenated column vectors of observables)
        """
        if norm:
            X = np.vstack([
                normalize(np.cos(np.radians(self.roll_angle))),
                normalize(np.sin(np.radians(self.roll_angle))),
                np.ones(len(self.bjd_time)),
            ]).T

        else:
            X = np.vstack([
                np.cos(np.radians(self.roll_angle)),
                np.sin(np.radians(self.roll_angle)),
                np.ones(len(self.bjd_time)),
            ]).T

        if self.extra_basis_vectors is not None:
            X = np.vstack([
                X.T, self.extra_basis_vectors,
            ]).T

        return X[~self.mask]
    
    def design_matrix_all(self, harmonics, norm=True):
        """
        Generate a design matrix that contains all possible detrending vectors

        Parameters:
        -----------
        harmonics : int
            Number of roll angle sinusoidal harmonics to be included
        norm : bool
            Normalize the column vectors within the design matrix such that they
            have mean=zero and range=unity.

        Returns
        -------
        X : `~numpy.ndarray`
            Design matrix (concatenated column vectors of observables)
        names : list
            List of names of each column
        """
        X = np.ones(len(self.bjd_time))
        name_detrend = ['ones']
        # Roll angle harmonics
        for i in range(harmonics):
            if norm:
                sin1 = normalize(np.sin((i+1)*np.radians(self.roll_angle)))
                cos1 = normalize(np.cos((i+1)*np.radians(self.roll_angle)))
            else:
                sin1 = np.sin((i+1)*np.radians(self.roll_angle))
                cos1 = np.cos((i+1)*np.radians(self.roll_angle))
            X = np.vstack([X, sin1])
            X = np.vstack([X, cos1])
            name_detrend.append('sin' + str(i+1))
            name_detrend.append('cos' + str(i+1))
        # Centroid positions, background
        try:
            xc, yc, bg = self.centroid_x, self.centroid_y, self.background
        except:
            xc, yc, bg = self.xc, self.yc, self.bg
        if norm:
            X = np.vstack([
                X, normalize(xc), normalize(yc), normalize(xc**2), normalize(yc**2), normalize(xc*yc), normalize(bg)
            ])
        else:
            X = np.vstack([
                X, xc, yc, xc**2, yc**2, xc*yc, bg
            ])
        name_detrend = name_detrend + ['xc', 'yc', 'x2', 'y2', 'xy', 'bg']
        # Contamination, smear for DRP; u1, u2 for PIPE
        try:
            if norm:
                X = np.vstack([X, normalize(self.conta_lc), normalize(self.smearing_lc)])
            else:
                X = np.vstack([X, self.conta_lc, self.smearing_lc])
            name_detrend = name_detrend + ['contamination', 'smearing']
        except:
            pass
        try:
            if norm:
                X = np.vstack([X, normalize(self.u1), normalize(self.u2)])
            else:
                X = np.vstack([X, self.u1, self.u2])
            name_detrend = name_detrend + ['u1', 'u2']
        except:
            pass
        X = X.T
        # Other extra basis vectors
        if self.extra_basis_vectors is not None:
            X = np.vstack([
                X.T, self.extra_basis_vectors,
            ]).T
            for i in range(len(self.extra_basis_vectors[:,0])):
                name_detrend.append('extra' + str(i+1))

        return X[~self.mask], name_detrend
        

    def sigma_clip_centroid(self, sigma=3.5, plot=False):
        """
        Sigma-clip the light curve on centroid position (update mask).

        Parameters
        ----------
        sigma : float
            Factor of standard deviations away from the median centroid position
            to clip on.
        plot : bool
            Plot the accepted centroids (in black) and the centroids of the
            rejected fluxes (in red).
        """
        x_mean = np.median(self.centroid_x)
        y_mean = np.median(self.centroid_y)
        x_std = mad_std(self.centroid_x)
        y_std = mad_std(self.centroid_y)

        outliers = (sigma * min([x_std, y_std]) <
                    np.hypot(self.centroid_x - x_mean,
                             self.centroid_y - y_mean))

        if plot:
            plt.scatter(self.centroid_x[~outliers], self.centroid_y[~outliers],
                        marker=',', color='k')
            plt.scatter(self.centroid_x[outliers], self.centroid_y[outliers],
                        marker='.', color='r')
            plt.xlabel('BJD')
            plt.ylabel('Flux')

        self.mask |= outliers

    def sigma_clip_flux(self, sigma_upper=4, sigma_lower=4, maxiters=None,
                        plot=False):
        """
        Sigma-clip the light curve on fluxes (update mask).

        Parameters
        ----------
        sigma_upper : float
            Factor of standard deviations above the median centroid position
            to clip on.
        sigma_lower : float
            Factor of standard deviations below the median centroid position
            to clip on.
        maxiters : float or None
            Number of sigma-clipping iterations. Default is None, which repeats
            until there are no outliers left.
        plot : bool
            Plot the accepted fluxes (in black) and the rejected fluxes (in red)
        """
        sc = SigmaClip(sigma_upper=sigma_upper, sigma_lower=sigma_lower,
                       stdfunc=mad_std, maxiters=maxiters)
        self.mask[~self.mask] |= sc(self.flux[~self.mask]).mask

        if plot:
            plt.plot(self.bjd_time[self.mask], self.flux[self.mask], 'r.')
            plt.plot(self.bjd_time[~self.mask], self.flux[~self.mask], 'k.')
            plt.xlabel('BJD')
            plt.ylabel('Flux')
    
    def high_bg_clip(self, bgmin=300, plot=False):
        """
        To mask the points with high background (mainly used for PIPE data)

        Parameters
        ----------
        bgmin : float
            Minimum threshold value of background, all points that have background
            above this value would be masked.
        plot : bool
            Plot the accepted fluxes (in black) and the rejected fluxes (in red)
        """
        msk = (self.bg > bgmin)
        self.mask |= msk
        
        if plot:
            plt.plot(self.bjd_time[self.mask], self.flux[self.mask], 'r.')
            plt.plot(self.bjd_time[~self.mask], self.flux[~self.mask], 'k.')
            plt.xlabel('BJD')
            plt.ylabel('Flux')
    
    def mask_planetary_signal(self, pl, plot=False):
        """
        To mask the points with planetary signal (transit/eclipse)

        Parameters
        ----------
        pl : Planet object
        plot : bool
            Plot the accepted fluxes (in black) and the rejected fluxes (in red)
        """
        # Planetary parameters
        per1 = pl.per
        ar1 = pl.a
        inc1 = np.deg2rad(pl.inc)
        rprs1 = pl.rp
        t01 = pl.t0             # Transit time
        t02 = pl.t0 + (per1/2)  # Eclipse time
        bb = ar1*np.cos(inc1)
        # Computing transit/eclipse duration
        ab = per1/np.pi
        cd = (1+rprs1)**2 - bb**2
        ef = 1 - ((bb/ar1)**2)
        br1 = (1/ar1)*(np.sqrt(cd/ef))
        t14 = ab*np.arcsin(br1)
        # Computing phase
        phs1 = ((self.bjd_time - t01)/per1) % 1        # Courtesy of `juliet`
        ii1 = np.where(phs1>0.5)[0]
        phs1[ii1] = phs1[ii1] - 1.
        phs2 = ((self.bjd_time - t02)/per1) % 1
        ii2 = np.where(phs2>0.5)[0]
        phs2[ii2] = phs2[ii2] - 1.
        # And producing the mask
        msk2 = (np.abs(phs1*per1)>=t14)&(np.abs(phs2*per1)>=t14)
        self.mask |= ~msk2
        if plot:
            plt.plot(self.bjd_time[self.mask], self.flux[self.mask], 'r.')
            plt.plot(self.bjd_time[~self.mask], self.flux[~self.mask], 'k.')
            plt.xlabel('BJD')
            plt.ylabel('Flux')


    def regress(self, design_matrix, log_lams=None):
        r"""
        Regress the design matrix against the fluxes.

        Parameters
        ----------
        design_matrix : `~numpy.ndarray`
            Design matrix (concatenated column vectors of observables)
        log_lams : `~numpy.ndarray`
            Array for regularisation strength

        Returns
        -------
        betas : `~numpy.ndarray`
            Least squares estimators :math:`\hat{\beta}`
        cov : `~numpy.ndarray`
            Covariance matrix for the least squares estimators
            :math:`\sigma_{\hat{\beta}}^2`
        """
        b, c = linreg(design_matrix,
                      self.flux[~self.mask],
                      self.fluxerr[~self.mask], log_lams)

        return RegressionResult(design_matrix, b, c)

    def plot_phase_curve(self, r, params, t_fine, transit_fine, sinusoid_fine,
                         t0_offset=0, n_regressors=2, bins=15):
        """
        Plot the best-fit phase curve.

        Parameters
        ----------
        r : `~linea.RegressionResult`
            Result of the linear regression
        params : `~linea.Planet`
            Transiting exoplanet parameters
        t_fine : `~numpy.ndarray`
            Times computed on a grid finer than the original observations
        transit_fine : `~numpy.ndarray`
            Transit model computed at times ``t_fine``
        sinusoid_fine : `~numpy.ndarray`
            Sinusoidal phase curve model computed at times ``t_fine``
        t0_offset : float, optional
            Time offset between the mid-transit time defined by ``params`` and
            the true mid-transit time [days]. Default is zero.
        n_regressors : int, optional
            Number of regressors used to parameterize the phase curve.
            Default is two.
        bins : int, optional
            Number of bins to break the light curve into when plotting (black),
            default is 15.

        Returns
        -------
        fig, ax : `~matplotlib.figure.Figure`, `~matplotlib.axes.Axes`
            Figure and axis objects containing the phase curve plot.
        """
        transit = r.X[:, 0]
        sinusoid = (r.X[:, 1:n_regressors+1] @ r.betas[1:n_regressors+1] /
                    r.best_fit)

        phases = ((self.bjd_time[~self.mask] - params.t0 - t0_offset) %
                  params.per) / params.per
        phases[phases > 0.95] -= 1
        phases_fine = (((t_fine - params.t0 - t0_offset) % params.per) /
                       params.per)
        phases_fine[phases_fine > 0.95] -= 1

        fig, ax = plt.subplots(2, 1, figsize=(4.5, 8), sharex=True)
        ax[0].plot(phases, (transit + 1) * (
                self.flux[~self.mask] / r.best_fit + sinusoid), '.',
                   color='silver')

        bs = binned_statistic(phases,
                              (transit + 1) * (self.flux[~self.mask] /
                                               r.best_fit + sinusoid),
                              bins=bins, statistic='median')
        bincenters = 0.5 * (bs.bin_edges[1:] + bs.bin_edges[:-1])

        ax[0].plot(bincenters, bs.statistic, 's', color='k')

        ax[0].plot(phases_fine[np.argsort(phases_fine)],
                   (transit_fine + sinusoid_fine)[np.argsort(phases_fine)], 'r')

        ax[0].set(ylabel='Phase Curve')

        bs_resid = binned_statistic(phases,
                                    self.flux[~self.mask] / r.best_fit - 1,
                                    bins=bins, statistic='median')

        ax[1].plot(phases, self.flux[~self.mask] / r.best_fit - 1, '.',
                   color='silver')
        ax[1].plot(bincenters, bs_resid.statistic, 's', color='k')

        ax[1].set(ylabel='Residuals', xlabel='Phase')
        ax[1].set_xticks(np.arange(-0, 1, 0.1), minor=True)

        for axis in ax:
            for sp in ['right', 'top']:
                axis.spines[sp].set_visible(False)
        ax[0].ticklabel_format(useOffset=False)

        return fig, ax

    def phase(self, planet_params):
        """
        Orbital phase of planet at times ``lc.bjd_time``.

        Parameters
        ----------
        planet_params : `~linea.Planet`
            Planet parameter object.

        Returns
        -------
        phases : `~numpy.ndarray`
            Orbital phases at times ``lc.bjd_time``
        """
        return (((self.bjd_time - planet_params.t0) % planet_params.per) /
                planet_params.per)


class JointLightCurve(object):
    """
    Joint analysis object for multiple CHEOPS light curves.
    """
    def __init__(self, light_curves):
        """
        Parameters
        ----------
        light_curves : list
            List of `~linea.CheopsLightCurve` objects.
        """
        self.light_curves = light_curves

        self.attrs = [attr.lower() for attr in
                      light_curves[0].recs.dtype.fields]

        for attr in self.attrs:
            if hasattr(self, attr):
                setattr(self, attr, [getattr(lc, attr) for lc in light_curves])

    @classmethod
    def from_example(cls, norm=True):
        """
        Load example WASP-189 b light curves (**NOTE**: this is not real data).

        Parameters
        ----------
        norm : bool
            Normalize the fluxes such that the median flux is unity. Default is
            True.
        """
        path = os.path.join(os.path.dirname(__file__), 'data',
                            'example_wasp189_*.fits')
        wasp189_light_curves = [CheopsLightCurve.from_fits(p, norm=norm)
                                for p in glob(path)]
        return cls(wasp189_light_curves)

    def concatenate(self):
        """
        Concatenate light curves into a single ``ConcatenatedLightCurve``.

        Returns
        -------
        c : `~collections.namedtuple`
            Named tuple containing the concatenated contents of the
            JointLightCurve object.
        """
        c = CheopsLightCurve(time=Time(np.concatenate([lc.time.jd
                                                      for lc in self]),
                                       format='jd'),
                             mask=np.concatenate([lc.mask for lc in self]))

        for attr in self.attrs:
            attr_to_concat = [getattr(lc, attr)
                              for lc in self
                              if hasattr(lc, attr)]
            setattr(c, attr, np.concatenate(attr_to_concat)
                    if len(attr_to_concat) > 0 else None)
        return c

    def _pad_shapes(self):
        shapes = []
        for lc in self:
            shapes.append(np.count_nonzero(~lc.mask))
        return shapes

    def combined_design_matrix(self, design_matrices=None, norm=True):
        """
        Generate the combined design matrix, from a list of design matrices, one
        per visit.

        Parameters
        ----------
        design_matrices : list of `~numpy.ndarray` (optional)
            List of design matrices, one per visit. If None is supplied, fetch
            the design matrices from each of the `~linea.CheopsLightCurve`
            objects used to initialize the `~linea.JointLightCurve`.

        Returns
        -------
        X : `~numpy.ndarray`
            Design matrix (concatenated column vectors of observables)
        """

        if design_matrices is None:
            design_matrices = [lc.design_matrix(norm=norm) for lc in self]

        shapes = self._pad_shapes()
        ndim = design_matrices[0].shape[1]
        Xs_padded = []

        for i in range(len(design_matrices)):
            before = shapes[:i]
            after = shapes[i+1:]

            prepad = np.zeros((sum(before), ndim)) if len(before) > 0 else None
            postpad = np.zeros((sum(after), ndim)) if len(after) > 0 else None

            segments = []
            for j in [prepad, design_matrices[i], postpad]:
                if j is not None:
                    segments.append(j)

            Xs_padded.append(np.vstack(segments))

        return np.hstack(Xs_padded)

    def __iter__(self):
        """
        When iterating over ``JointLightCurve`` objects, iterate over items in
        the ``self.light_curves`` list used to initialize the object.
        """
        yield from self.light_curves

    def __len__(self):
        return len(self.light_curves)

    def __getitem__(self, item):
        return self.light_curves[item]

    def regress(self, design_matrix):
        r"""
        Regress the design matrix against the fluxes.

        Parameters
        ----------
        design_matrix : `~numpy.ndarray`
            Design matrix (concatenated column vectors of observables)

        Returns
        -------
        betas : `~numpy.ndarray`
            Least squares estimators :math:`\hat{\beta}`
        cov : `~numpy.ndarray`
            Covariance matrix for the least squares estimators
            :math:`\sigma_{\hat{\beta}}^2`
        """
        flux = np.concatenate([lc.flux for lc in self])
        fluxerr = np.concatenate([lc.fluxerr for lc in self])
        mask = np.concatenate([lc.mask for lc in self])

        b, c = linreg(design_matrix,
                      flux[~mask],
                      fluxerr[~mask])

        return RegressionResult(design_matrix, b, c)

    def plot(self, ax=None, **kwargs):
        """
        Plot the light curve.

        Parameters
        ----------
        ax : `~matplotlib.axes.Axes`
            Matplotlib axis instance on which to build the plot
        kwargs : dict
            Further keyword arguments to pass to `~matplotlib.pyplot.plot`.

        Returns
        -------
        ax : `~matplotlib.axes.Axes`
            Matplotlib axis instance with the light curve plotted on it.
        """
        if ax is None:
            ax = plt.gca()

        for lc in self:
            ax.errorbar(lc.bjd_time[~lc.mask], lc.flux[~lc.mask],
                        lc.fluxerr[~lc.mask], **kwargs)

        return ax