import { useCallback } from 'react';
import { useOrganizationStore } from '@/lib/stores/organizations';

export interface UseOrganizationContext {
  // State
  organizations: Array<{
    id: string;
    name: string;
    description?: string;
    role: 'owner' | 'admin' | 'member';
    is_primary: boolean;
    created_at?: string;
    modified_at?: string;
  }>;
  currentOrganization: {
    id: string;
    name: string;
    description?: string;
    role: 'owner' | 'admin' | 'member';
    is_primary: boolean;
    created_at?: string;
    modified_at?: string;
  } | null;
  isLoading: boolean;

  // Actions
  fetchOrganizations: () => Promise<void>;
  createOrganization: (data: { name: string; description?: string }) => Promise<any>;
  switchOrganization: (orgId: string) => void;
  updateOrganization: (orgId: string, updates: { name?: string; description?: string }) => void;

  // Utility functions
  canManageOrganization: (orgId?: string) => boolean;
  canDeleteOrganization: (orgId?: string) => boolean;
  isCurrentUserOwner: (orgId?: string) => boolean;
  isCurrentUserAdmin: (orgId?: string) => boolean;
}

export const useOrganizationContext = (): UseOrganizationContext => {
  const {
    organizations,
    currentOrganization,
    isLoading,
    fetchUserOrganizations,
    createOrganization,
    switchOrganization,
    updateOrganization,
  } = useOrganizationStore();

  const fetchOrganizations = useCallback(async () => {
    await fetchUserOrganizations();
  }, [fetchUserOrganizations]);

  const canManageOrganization = useCallback((orgId?: string) => {
    const org = orgId
      ? organizations.find(o => o.id === orgId)
      : currentOrganization;

    return org ? ['owner', 'admin'].includes(org.role) : false;
  }, [organizations, currentOrganization]);

  const canDeleteOrganization = useCallback((orgId?: string) => {
    const org = orgId
      ? organizations.find(o => o.id === orgId)
      : currentOrganization;

    return org ? org.role === 'owner' : false;
  }, [organizations, currentOrganization]);

  const isCurrentUserOwner = useCallback((orgId?: string) => {
    const org = orgId
      ? organizations.find(o => o.id === orgId)
      : currentOrganization;

    return org ? org.role === 'owner' : false;
  }, [organizations, currentOrganization]);

  const isCurrentUserAdmin = useCallback((orgId?: string) => {
    const org = orgId
      ? organizations.find(o => o.id === orgId)
      : currentOrganization;

    return org ? ['owner', 'admin'].includes(org.role) : false;
  }, [organizations, currentOrganization]);

  return {
    // State
    organizations,
    currentOrganization,
    isLoading,

    // Actions
    fetchOrganizations,
    createOrganization,
    switchOrganization,
    updateOrganization,

    // Utility functions
    canManageOrganization,
    canDeleteOrganization,
    isCurrentUserOwner,
    isCurrentUserAdmin,
  };
};
