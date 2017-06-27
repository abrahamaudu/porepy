import numpy as np
import scipy.sparse as sps

from porepy.numerics.mixed_dim.abstract_coupling import AbstractCoupling


class UpwindCoupling(AbstractCoupling):

#------------------------------------------------------------------------------#

    def __init__(self, solver):
        self.solver = solver

#------------------------------------------------------------------------------#

    def matrix_rhs(self, g_h, g_l, data_h, data_l, data_edge):
        """
        Construct the matrix (and right-hand side) for the coupling conditions.
        Note: the right-hand side is not implemented now.

        Parameters:
            g_h: grid of higher dimension
            g_l: grid of lower dimension
            data_h: dictionary which stores the data for the higher dimensional
                grid
            data_l: dictionary which stores the data for the lower dimensional
                grid
            data: dictionary which stores the data for the edges of the grid
                bucket

        Returns:
            cc: block matrix which store the contribution of the coupling
                condition. See the abstract coupling class for a more detailed
                description.
        """

        # Normal component of the velocity from the higher dimensional grid
        beta_n = data_edge['beta_n']
        assert beta_n is not None

        # Retrieve the number of degrees of both grids
        # Create the block matrix for the contributions
        dof, cc = self.create_block_matrix(g_h, g_l)

        # 1d-1d
        if g_h.dim == g_l.dim:
            faces_h, faces_l, _ = sps.find(data_edge['face_cells'])

            faces0, _, sgn_h = sps.find(g_h.cell_faces)
            sgn_h = sgn_h[np.unique(faces0, return_index=True)[1]]
            beta_n_h = sgn_h[faces_h] * beta_n[faces_h]

            faces1, _, sgn_l = sps.find(g_l.cell_faces)
            sgn_l = sgn_l[np.unique(faces1, return_index=True)[1]]
            # obs beta_n SHOULD be indexed by faces_h, as it per convention is
            # extracted from that grid (second in gb.sorted_nodes_of_edge):
            beta_n_l = sgn_l[faces_l] * beta_n[faces_h]

            # Determine which cells correspond to the faces
            cell_faces_h = g_h.cell_faces.tocsr()[faces_h, :]
            cells_h = cell_faces_h.nonzero()[1]
            cell_faces_l = g_l.cell_faces.tocsr()[faces_l, :]
            cells_l = cell_faces_l.nonzero()[1]

            diag_cc11 = np.zeros(g_l.num_cells)
            np.add.at(diag_cc11, cells_l, np.sign(
                beta_n_l.clip(min=0)) * beta_n_l)
            diag_cc00 = np.zeros(g_h.num_cells)
            np.add.at(diag_cc11, cells_h, np.sign(
                beta_n_h.clip(min=0)) * beta_n_h)

            # Compute the outflow from the second to the first grid
            cc[1, 0] = sps.coo_matrix((beta_n_l.clip(max=0), (cells_l, cells_h)),
                                      shape=(dof[1], dof[0]))

            # Compute the inflow from the first to the second grid
            cc[0, 1] = sps.coo_matrix((beta_n_h.clip(max=0), (cells_h, cells_l)),
                                      shape=(dof[0], dof[1]))

        else:
            # Recover the information for the grid-grid mapping
            cells_l, faces_h, _ = sps.find(data_edge['face_cells'])

            # Recover the correct sign for the velocity
            faces, _, sgn = sps.find(g_h.cell_faces)
            sgn = sgn[np.unique(faces, return_index=True)[1]]
            beta_n = sgn[faces_h] * beta_n[faces_h]

            # Determine which are the corresponding cells of the faces_h
            cell_faces_h = g_h.cell_faces.tocsr()[faces_h, :]
            cells_h = cell_faces_h.nonzero()[1]

            diag_cc11 = np.zeros(g_l.num_cells)
            np.add.at(diag_cc11, cells_l, np.sign(beta_n.clip(max=0)) * beta_n)

            diag_cc00 = np.zeros(g_h.num_cells)
            np.add.at(diag_cc00, cells_h, np.sign(beta_n.clip(min=0)) * beta_n)
            # Compute the outflow from the higher to the lower dimensional grid
            cc[1, 0] = sps.coo_matrix((-beta_n.clip(min=0), (cells_l, cells_h)),
                                      shape=(dof[1], dof[0]))

            # Compute the inflow from the higher to the lower dimensional grid
            cc[0, 1] = sps.coo_matrix((beta_n.clip(max=0), (cells_h, cells_l)),
                                      shape=(dof[0], dof[1]))

        cc[1, 1] = sps.dia_matrix((diag_cc11, 0), shape=(dof[1], dof[1]))

        cc[0, 0] = sps.dia_matrix((diag_cc00, 0), shape=(dof[0], dof[0]))
        return cc

#------------------------------------------------------------------------------#

    def cfl(self, g_h, g_l, data_h, data_l, data_edge):
        """
        Return the time step according to the CFL condition.
        Note: the vector field is assumed to be given as the normal velocity,
        weighted with the face area, at each face.

        The name of data in the input dictionary (data) are:
        beta_n : array (g.num_faces)
            Normal velocity at each face, weighted by the face area.

        Parameters:
            g_h: grid of higher dimension
            g_l: grid of lower dimension
            data_h: dictionary which stores the data for the higher dimensional
                grid
            data_l: dictionary which stores the data for the lower dimensional
                grid
            data: dictionary which stores the data for the edges of the grid
                bucket

        Return:
            deltaT: time step according to CFL condition.

        """
        # Retrieve the beta_n, which is mandatory
        beta_n = data_edge['beta_n']

        # Recover the information for the grid-grid mapping
        cells_l, faces_h, _ = sps.find(data_edge['face_cells'])

        # Detect and remove the faces which have zero in "beta_n"
        not_zero = ~np.isclose(np.zeros(faces_h.size), beta_n[faces_h], atol=0)
        if not np.any(not_zero):
            return np.inf

        cells_l = cells_l[not_zero]
        faces_h = faces_h[not_zero]
        # Mapping from faces_h to cell_h
        cell_faces_h = g_h.cell_faces.tocsr()[faces_h, :]
        cells_h = cell_faces_h.nonzero()[1][not_zero]
        # Retrieve and map additional data
        apertures_h = data_h.get('a', np.ones(g_h.num_cells))[cells_h]
        apertures_l = data_l.get('a', np.ones(g_l.num_cells))[cells_l]
        phi_l = data_l.get('phi', np.ones(g_l.num_cells))[cells_l]
        # Compute discrete distance cell to face centers for the lower
        # dimensional grid
        dist = 0.5 * np.divide(apertures_l, apertures_h)
        # Since beta_n is multiplied by the aperture, we get rid of it!!!!
        beta_n = np.divide(beta_n[faces_h], g_h.face_areas[faces_h]*apertures_h)
        # deltaT is deltaX/beta_n with coefficient
        return np.amin(np.abs(np.divide(dist, beta_n)) * phi_l)

#------------------------------------------------------------------------------#
