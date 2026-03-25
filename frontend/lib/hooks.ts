"use client";

import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "./api-client";
import type { NovelCreateParams } from "./types";

// ─── Projects ────────────────────────────────────────────────────────
export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.getProjects(),
  });
}

// ─── Tasks ───────────────────────────────────────────────────────────
export function useTasks(limit?: number) {
  const query = useQuery({
    queryKey: ["tasks", limit],
    queryFn: () => api.getTasks(limit),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some(
        (t) => t.status === "pending" || t.status === "running"
      );
      return hasActive ? 3000 : false;
    },
  });
  return query;
}

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.getTask(taskId!),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      if (data.status === "pending" || data.status === "running") return 2000;
      return false;
    },
  });
}

export function useCancelTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api.cancelTask(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api.deleteTask(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

// ─── Novels ──────────────────────────────────────────────────────────
export function useNovels() {
  return useQuery({
    queryKey: ["novels"],
    queryFn: () => api.listNovels(),
  });
}

export function useNovel(id: string | null) {
  return useQuery({
    queryKey: ["novel", id],
    queryFn: () => api.getNovel(id!),
    enabled: !!id,
  });
}

export function useCreateNovel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: NovelCreateParams) => api.createNovel(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novels"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useGenerateChapters(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params?: any) => api.generateChapters(novelId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function usePolishChapters(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params?: any) => api.polishChapters(novelId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useAnalyzeFeedback(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.analyzeFeedback(novelId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useApplyFeedback(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.applyFeedback(novelId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useEditNovel(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.editNovel(novelId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function useResizeNovel(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (newTotal: number) => api.resizeNovel(novelId, newTotal),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function usePublishChapters(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ chapters, published }: { chapters: number[]; published: boolean }) =>
      api.publishChapters(novelId, chapters, published),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function useAgentChat(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ message, contextChapters, history }: { message: string; contextChapters?: number[]; history?: Array<{role: string; content: string}> }) =>
      api.agentChat(novelId, message, contextChapters, history),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useChapter(novelId: string, chapterNum: number | null) {
  return useQuery({
    queryKey: ["chapter", novelId, chapterNum],
    queryFn: () => api.getChapter(novelId, chapterNum!),
    enabled: !!novelId && chapterNum !== null && chapterNum > 0,
  });
}

export function useSaveChapter(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ chapterNum, text }: { chapterNum: number; text: string }) =>
      api.saveChapter(novelId, chapterNum, text),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["chapter", novelId, vars.chapterNum] });
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function useProofreadChapter(novelId: string) {
  return useMutation({
    mutationFn: (chapterNum: number) =>
      api.proofreadChapter(novelId, chapterNum),
  });
}

export function useApplyFixes(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      chapterNum: number;
      text: string;
      issues: any[];
      selectedIndices: number[];
    }) =>
      api.applyFixes(
        novelId,
        params.chapterNum,
        params.text,
        params.issues,
        params.selectedIndices
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["chapter", novelId, vars.chapterNum] });
    },
  });
}

export function useNovelSettings(novelId: string) {
  return useQuery({
    queryKey: ["novel-settings", novelId],
    queryFn: () => api.getNovelSettings(novelId),
    enabled: !!novelId,
  });
}

export function useSaveNovelSettings(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: any) => api.saveNovelSettings(novelId, settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel-settings", novelId] });
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function useAnalyzeSettingImpact(novelId: string) {
  return useMutation({
    mutationFn: (params: any) => api.analyzeSettingImpact(novelId, params),
  });
}

export function useRewriteAffected(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (impact: any) => api.rewriteAffected(novelId, impact),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function usePolishDiff(novelId: string, chapterNum: number | null) {
  return useQuery({
    queryKey: ["polish-diff", novelId, chapterNum],
    queryFn: () => api.getPolishDiff(novelId, chapterNum!),
    enabled: !!novelId && chapterNum !== null && chapterNum > 0,
  });
}

export function useExportNovel(novelId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.exportNovel(novelId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novel", novelId] });
    },
  });
}

export function useDeleteNovel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteNovel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["novels"] });
    },
  });
}

// ─── Videos ──────────────────────────────────────────────────────────
export function useVideos() {
  return useQuery({
    queryKey: ["videos"],
    queryFn: () => api.listVideos(),
  });
}

export function useVideoTasks(limit: number = 100) {
  return useQuery({
    queryKey: ["video-tasks", limit],
    queryFn: async () => {
      const tasks = await api.getTasks(limit);
      return tasks.filter(
        (t) =>
          t.task_type === "video_generate" ||
          t.task_type === "director_generate"
      );
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some(
        (t) => t.status === "pending" || t.status === "running"
      );
      return hasActive ? 5000 : false;
    },
  });
}

export function useVideo(id: string | null) {
  return useQuery({
    queryKey: ["video", id],
    queryFn: () => api.getVideo(id!),
    enabled: !!id,
  });
}

export function useCreateVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.createVideo(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["videos"] });
      qc.invalidateQueries({ queryKey: ["video-tasks"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

// ─── PPT ─────────────────────────────────────────────────────────────
export function usePPTs() {
  return useQuery({
    queryKey: ["ppt"],
    queryFn: () => api.listPPT(),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some(
        (p) => p.status === "running" || (p as any).status === "in_progress"
      );
      return hasActive ? 5000 : false;
    },
  });
}

export function usePPT(id: string | null) {
  return useQuery({
    queryKey: ["ppt", id],
    queryFn: () => api.getPPT(id!),
    enabled: !!id,
    refetchInterval: 10000,
  });
}

export function useCreatePPT() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.createPPT(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ppt"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useContinuePPT(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: any) => api.continuePPT(projectId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ppt", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useRenderPPT(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params?: any) => api.renderPPT(projectId, params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ppt", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useExportPPT(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.exportPPT(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ppt", projectId] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}
