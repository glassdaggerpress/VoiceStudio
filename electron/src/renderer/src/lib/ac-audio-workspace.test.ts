import { describe, expect, it } from 'vitest';
import { audioWorkspaceModel } from './ac-audio-workspace';

describe('Audio Studio model context', () => {
  it('selects the design model and remembers the selected cloning quality', () => {
    expect(audioWorkspaceModel('/design', 'qwen3-tts-quality', null)).toEqual({model:'qwen3-tts',rememberClone:'qwen3-tts-quality'});
  });
  it('restores that cloning model for dubbing', () => {
    expect(audioWorkspaceModel('/dub', 'qwen3-tts', 'qwen3-tts-quality')).toEqual({model:'qwen3-tts-quality',rememberClone:null});
  });
  it('keeps an explicitly selected cloning alternative', () => {
    expect(audioWorkspaceModel('/clone', 'qwen3-tts-quality', null)).toBeNull();
  });
  it('does not override model selection while browsing the catalogue', () => {
    expect(audioWorkspaceModel('/settings/models', 'qwen3-tts', null)).toBeNull();
  });
});
