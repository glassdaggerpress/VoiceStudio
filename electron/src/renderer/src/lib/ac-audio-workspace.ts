const DESIGN = 'qwen3-tts';
const DESIGN_REPO = 'mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit';

export function audioWorkspaceModel(path: string, current: string, savedClone: string | null) {
  if (path === '/design' && current !== DESIGN && current !== DESIGN_REPO)
    return { model: DESIGN, rememberClone: current };
  if ((path === '/clone' || path === '/dub') && (current === DESIGN || current === DESIGN_REPO))
    return { model: savedClone || 'qwen3-tts-base', rememberClone: null };
  return null;
}
