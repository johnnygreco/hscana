import cuts
import pipeTools
import numpy as np
from astropy.table import Table

class MyCat:
    """
    This class builds a catalog of objects within an HSC tract and patch. 
    If a galaxy group id or redshift is given, then properties such as physical size 
    and absolute magnitude are calculated assuming the redshift to the group. 
    Currently, selection cuts are stored as dictionaries in cuts.py, and a 
    group id must be given to make the size and absolute magnitude cuts.

    Initialization Parameters
    -------------------------
    tract : int
        HSC tract number.
    patch : string
        HSC patch. e.g., '5,7'.
    band : string, optional
        The photometric band of the observation ('G', 'R', 'I', 'Z', or 'Y').
    group_id : int, optional 
        The galaxy group id number
    group_z : float, optional
        The redshift to the group
    usewcs : bool, opional
        If True, use the WCS to calculate the angular sizes.
    makecuts : bool, optional
        If True, make all cuts to the catalog during the initialization
    butler : Butler object, optional
        If None, will create a butler at initialization

    Note: The kwargs may be used for the optional arguments to the 
          pipeTools.py functions.
    """
    def __init__(self, tract, patch, band='I', group_id=None, group_z=None, usewcs=False, makecuts=False, butler=None, **kwargs):

        # If creating many mycat objects, you should create one bulter object for intialization.
        if butler is None:
            butler = pipeTools.get_butler()

        # Get catalog and exposure for this tract, patch, & band.
        self.exp = pipeTools.get_exp(tract, patch, band, butler)
        self.wcs = self.exp.getWcs() if usewcs else None
        self.cat = pipeTools.get_cat(tract, patch, band, butler)
        self.count_record = [] # record of number of objects
        self.count(update_record=True)

        # Calculate angular size, apparent mag,and surface 
        # brightness for all objects in the catalog.
        self.angsize = pipeTools.get_angsize(self.cat, wcs=self.wcs, **kwargs)
        self.mag = pipeTools.get_mag(self.cat, self.exp.getCalib(), **kwargs)
        self.SB = pipeTools.get_SB(mag=self.mag, angsize=self.angsize)
        self.ra = self.cat.get('coord.ra')*180.0/np.pi
        self.dec = self.cat.get('coord.dec')*180.0/np.pi

        # If a group_id is given, calculate sizes (in kpc) 
        # and absolute mags for objects
        self.group_id = group_id
        self.group_z = group_z
        if (group_id is not None) or (group_z is not None):
            self.calc_group_params(group_id, group_z)

        # If makecuts=True, then make the selection cuts now.
        if makecuts:
            self.make_cuts()

    def calc_group_params(self, group_id=None, group_z=None):
        """
        Calculate physical parameters for all objects in the current 
        catalog assuming the redshift of the galaxy group with id = group_id.

        Parameter
        ---------
        group_id : int
            The galaxy group identification number.
        """
        if group_z is not None:
            from toolbox.cosmo import Cosmology
            cosmo = Cosmology()
            self.D_A, self.D_L, self.group_z = cosmo.D_A(group_z), cosmo.D_L(group_z), group_z
            self.size = self.angsize*self.D_A*(1.0/206265.)*1.0e3      # size in kpc
            self.absmag = pipeTools.get_absmag(self.D_L, mag=self.mag)  # absolute magnitude
        elif group_id is not None:
            self.group_id = group_id
            group_info = Table.read('/home/jgreco/data/groups/group_info.csv')
            idx = np.argwhere(group_info['group_id']==group_id)[0,0]
            self.D_A, self.D_L, self.group_z = group_info['D_A', 'D_L', 'z'][idx]
            self.size = self.angsize*self.D_A*(1.0/206265.)*1.0e3      # size in kpc
            self.absmag = pipeTools.get_absmag(self.D_L, mag=self.mag)  # absolute magnitude
        else:
            print 'Need group_id or redshift to calculate group params!'

    def coord(self):
        """
        Get coordinates for all objects in catalog.

        Returns
        -------
        coords : ndarray, shape = (N objects, 2)
            Coordinates (ra, dec) in degrees.
        """
        return np.dstack((self.ra, self.dec))[0]

    def count(self, update_record=False):
        """
        Count number of objects in current catalog.
        
        Parameter
        ---------
        update_record : bool, optional
            If True, update the count record, which is a list
            that saves the number of objects after each cut.

        Returns
        -------
        counts : int, only returns if update_record=False
            The number of objects in the current catalog.
        """
        num = len(self.cat)
        if update_record:
            self.count_record.append(num)
        else:
            return num

    def apply_cuts(self, cut):
        """
        Apply cuts in cut = ndarray of bools to the catalog and 
        all derived properties, and update the count record.
        """
        self.cat = self.cat[cut].copy(deep=True)
        self.angsize = self.angsize[cut]
        self.mag = self.mag[cut]
        self.SB = self.SB[cut]
        self.ra = self.ra[cut]
        self.dec = self.dec[cut]
        if self.group_id or self.group_z:
            self.size = self.size[cut]
            self.absmag = self.absmag[cut]
        self.count(update_record=True)

    def make_cuts(self):
        """
        Build the cut mask and apply cuts with above method. We keep
        two records as dictionaries:

        cut_record : a record of how many objects get cut by each cut 
        nan_record : a record of how many objects get cut due to a 
            derived property (e.g., size, magnitude) begin NaN. 
        """
        from cuts import cat_cuts, phy_cuts

        # source and bad pixel cuts: the "catalog cuts"
        self.cut_record = {}
        cut  = np.ones(len(self.cat), dtype=bool)
        for col, val in cat_cuts.iteritems():
            if val is not None:
                _c = self.cat.get(col) == val
                self.cut_record.update({col:(~_c).sum()})
                cut &= _c
        self.apply_cuts(cut)

        # size, abs mag, and SB cuts: the "physical cuts"
        self.nan_record = {}
        self.nan_record.update({'mag':np.isnan(self.mag).sum()})
        if phy_cuts['SB_min'] is not None:
            self.SB[np.isnan(self.SB)] = -999.
            cut = self.SB > phy_cuts['SB_min']
            self.apply_cuts(cut)
            self.cut_record.update({'SB_min':(~cut).sum()})
        if phy_cuts['SB_max'] is not None:
            cut = self.SB < phy_cuts['SB_max']
            self.apply_cuts(cut)
            self.cut_record.update({'SB_max':(~cut).sum()})
        if (self.group_id is None) and (self.group_z is None):
            print '*** no group id or redshift given, so no size or abs mag cuts'
        else:
            self.nan_record.update({'size':np.isnan(self.size).sum()})
            if phy_cuts['size_min'] is not None:
                self.size[np.isnan(self.size)] = -999.
                cut = self.size > phy_cuts['size_min']
                self.apply_cuts(cut)
                self.cut_record.update({'size_min':(~cut).sum()})
            if phy_cuts['absmag_max'] is not None:
                cut = self.absmag < phy_cuts['absmag_max']
                self.apply_cuts(cut)
                self.cut_record.update({'absmag_max':(~cut).sum()})

if __name__=='__main__':
    group_id = 1925
    tract = 9347
    patch = '5,8'
    mycat = MyCat(tract, patch)
