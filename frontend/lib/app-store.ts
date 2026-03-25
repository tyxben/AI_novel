"use client";

import { create } from "zustand";
import type { WorkspaceKind } from "@/lib/types";

type AppState = {
  activeWorkspace: WorkspaceKind | null;
  selectedProjectId: string | null;
  setActiveWorkspace: (workspace: WorkspaceKind | null) => void;
  setSelectedProjectId: (id: string | null) => void;
};

export const useAppStore = create<AppState>((set) => ({
  activeWorkspace: null,
  selectedProjectId: null,
  setActiveWorkspace: (activeWorkspace) => set({ activeWorkspace }),
  setSelectedProjectId: (selectedProjectId) => set({ selectedProjectId })
}));
