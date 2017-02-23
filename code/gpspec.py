import os
import math
import numpy as np
from sklearn.decomposition import PCA as sklPCA
from lsst_utils.Sed import Sed
from lsst_utils.BandpassDict import BandpassDict


class pcaUtils(object):
    """Contains utilities for all other PCA routines."""

    def loadSpectra(self, directory):
        """
        Read in spectra from files in given directory.

        Parameters
        ----------
        directory: str
            Location of spectra files.

        Returns
        -------
        spec_list: list of Sed class instances
            List where each entry is an instance of the Sed class containing
            the information for one model spectrum.
        """
        spec_list = []
        for root, dirs, files in os.walk(directory):
            fileTotal = len(files)
            fileOn = 1
            for name in files:
                if fileOn % 100 == 0:
                    print str("File On " + str(fileOn) + " out of " +
                              str(fileTotal))
                fileOn += 1
                try:
                    spec = Sed()
                    spec.readSED_flambda(os.path.join(root, name))
                    spec.name = name
                    if math.isnan(spec.flambda[0]) is False:
                        spec_list.append(spec)
                except:
                    continue

        return spec_list

    def scaleSpectrum(self, sedFlux):
        """
        Norm spectrum so adds up to 1.

        Parameters
        ----------
        sedFlux: array
            The flux array of an SED.

        Returns
        -------
        normSpec: array
            The normalized flux array.
        """
        norm = np.sum(sedFlux)
        normSpec = sedFlux/norm

        return normSpec


class pcaSED(pcaUtils):
    """
    When given a directory containing spectra. This class will create sets
    of eigenspectra in bins created based upon the distribution in color-color
    space. It will also provide the given principal components to recreate
    the spectra using the sets of eigenspectra.

    Parameters
    ----------
    directory: str
        Directory where the model spectra are stored.

    bandpassDir: str
        Location of bandpass files. Default is LSST stack's location for LSST
        filters.

    bandpassRoot: str, default: 'total_'
        Root for filenames of bandpasses. Default are LSST Total Bandpasses.

    filters: list, default: ['u', 'g', 'r', 'i', 'z', 'y']
        Name of filters to be used for calculating colors. Default are
        LSST bands.

    Attributes
    ----------
    cluster_centers: array, [n_bins, n_colors]
        Location in color-color space of the bin centers used in grouping the
        model spectra if n_bins > 1.

    meanSpec: array, [n_bins, n_wavelengths]
        The mean spectrum of each bin. Needs to be added back in when
        reconstructing the spectra from
        principal components.

    eigenspectra: array, [n_bins, n_components, n_wavelengths]
        These are the eigenspectra derived from the PCA organized by bin.

    projected: array, [n_bins, n_binMembers, n_components]
        These are the principal components for each model spectrum
        organized by bin.

    binnedNames: list, [n_bins, n_binMembers]
        The names of the model spectra in each bin. Used when writing output.

    temps: array, (only when using blackbodyPCA), [n_bins, n_binMembers]
        The temperatures of the blackbody spectrum divided out of the model
        spectrum and needed in order to reconstruct the spectrum.

    pcaType: str
        'BB' or 'NoBB' depending on which method is used to calculate PCA.
        Used to keep track of what to write to output and when reconstructing
        in other methods.
    """
    def __init__(self, directory, bandpass_dir, bandpass_root='total_',
                 filters=['u', 'g', 'r', 'i', 'z', 'y']):

        self.spec_list_orig = self.loadSpectra(directory)
        print 'Done loading spectra from file'

        self.filters = filters
        self.bandpass_dict = BandpassDict.loadTotalBandpassesFromFiles(
                                                  bandpassNames=self.filters,
                                                  bandpassDir=bandpass_dir,
                                                  bandpassRoot=bandpass_root)

    def specPCA(self, comps, minWavelen=299., maxWavelen=1200.):
        """
        Read in spectra, then calculate the colors.
        Bin the spectra by their colors and then perform the PCA on each bin
        separately.

        Parameters
        ----------
        comps: int
            Maximum number of principal components desired.

        minWavelen: float, optional, default = 299.
            Minimum wavelength of spectra to use in creating PCA. Can speed up
            PCA and minimize number of components needed for accuracy in a
            defined range.

        maxWavelen: float, optional, default = 1200.
            Maximum wavelength of spectra to use in creating PCA. Can speed up
            PCA and minimize number of components needed for accuracy in a
            defined range.
        """
        self.spec_list = []

        # Resample the spectra over the desired wavelength range. This will
        # make PCA more accurate where we care about and faster.
        min_wave_x = np.where(self.spec_list_orig[0].wavelen >=
                              minWavelen)[0][0]
        max_wave_x = np.where(self.spec_list_orig[0].wavelen <=
                              maxWavelen)[0][-1]
        wavelen_set = self.spec_list_orig[0].wavelen[min_wave_x:max_wave_x+1]

        full_mags = []
        scaled_fluxes = []

        for spec in self.spec_list_orig:

            # Calculate Mags and save resampled and normalized copies of SEDs
            temp_spec = Sed()
            temp_spec.setSED(wavelen=spec.wavelen, flambda=spec.flambda)
            temp_mags = np.array(self.bandpass_dict.magListForSed(temp_spec))
            full_mags.append(temp_mags)
            temp_spec.resampleSED(wavelen_match=wavelen_set)
            temp_spec.scale_flux = self.scaleSpectrum(temp_spec.flambda)
            scaled_fluxes.append(temp_spec.scale_flux)
            temp_spec.name = spec.name
            self.spec_list.append(temp_spec)

        # Get colors from the mags calculated above.
        full_mags_T = np.transpose(np.array(full_mags))
        color_vals = []
        for color_num in range(0, len(full_mags_T)-1):
            color_vals.append(full_mags_T[color_num] -
                              full_mags_T[color_num+1])

        """
        Calculate the eigenspectra from each bin. Also, keep the mean spectrum
        for each bin. Then project the model spectra in each bin onto the
        eigenspectra and keep the desired number of principal components.
        """
        spectra_pca = sklPCA(n_components=comps)
        spectra_pca.fit(scaled_fluxes)
        self.mean_spec = spectra_pca.mean_
        self.eigenspectra = spectra_pca.components_
        self.projected = np.array(spectra_pca.transform(scaled_fluxes))
        self.explained_var = spectra_pca.explained_variance_ratio_

        full_mags = np.array(full_mags)
        color_vals = np.array(color_vals)
        self.mags = full_mags
        self.colors = color_vals.T

    def reconstruct_spectra(self, num_comps):
        """
        Reconstruct spectrum using only num_comps principal components.

        Parameters
        ----------
        num_comps: int
        Number of principal components to use to reconstruct spectra.

        Returns
        -------
        reconstructed_specs: numpy array
        The reconstructed spectra in an (m,n) = (# of spectra, # of wavelength)
        shape array.
        """
        reconstructed_specs = self.mean_spec + \
            np.dot(self.projected[:, :num_comps], self.eigenspectra)

        return reconstructed_specs

    def calc_new_colors(self, num_comps):
        """
        Calculate the colors using only num_comps principal components.

        Parameters
        ----------
        num_comps: int
        Number of principal components to use to calculate spectra colors.

        Returns
        -------
        reconstructed_colors: numpy array
        Colors calculated with reconstructed spectra in an
        (m,n) = (# of spectra, # of colors) shape array.
        """
        reconstructed_specs = self.reconstruct_spectra(num_comps)

        reconstructed_colors = []
        for spec in reconstructed_specs:
            new_spec = Sed()
            new_spec.setSED(wavelen=self.spec_list[0].wavelen,
                            flambda=spec)
            mags = np.array(self.bandpass_dict.magListForSed(new_spec))
            colors = [mags[x] - mags[x-1] for x in range(len(self.filters)-1)]
            reconstructed_colors.append(colors)

        return np.array(reconstructed_colors)

    def write_output(self, outFolder):
        """
        This routine will write out the eigenspectra, eigencomponents,
        mean spectrum and wavelength grid to files in a specified output
        directory with a separate folder for each bin.

        Parameters
        ----------
        outFolder = str
            Folder where information will be stored.
        """

        np.savetxt(str(outFolder + '/wavelengths.dat'),
                   self.spec_list[0].wavelen)

        specPath = str(outFolder + '/eigenspectra')
        os.makedirs(specPath)
        for spec, specNum in zip(self.eigenspectra,
                                 range(0, len(self.eigenspectra))):
            np.savetxt(str(specPath + '/eigenspectra_' +
                           str(specNum) + '.dat'), spec)

        compPath = str(outFolder + '/components')
        os.makedirs(compPath)
        for spec, comps in zip(self.spec_list, self.projected):
            specName = spec.name
            np.savetxt(str(compPath + '/' + specName + '.dat'), comps)

        np.savetxt(str(outFolder + '/meanSpectrum.dat'), self.mean_spec)