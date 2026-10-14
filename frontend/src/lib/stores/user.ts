import { create } from 'zustand';

interface UserState {
  user: any | null;
  setUser: (user: any | null) => void;
  currentOrg: any | null;
  setCurrentOrg: (org: any | null) => void;
}

const useUserStore = create<UserState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  currentOrg: null,
  setCurrentOrg: (org) => set({ currentOrg: org }),
}));

export default useUserStore;
