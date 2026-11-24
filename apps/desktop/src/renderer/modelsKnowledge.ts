import { formatGb, ModelRecommendations } from './chats';

export interface ModelKnowledge {
  tag: string;
  displayName: string;
  family: string;
  author: string;
  license: string;
  contextWindow: string;
  specialtyHeadline: string;
  bestFor: string[];
  strengths: string[];
  considerations: string[];
  scores: {
    coding: number;
    toolCalling: number;
    reasoning: number;
    speed: number;
  };
  keyTags: string[];
}

export const MODEL_KNOWLEDGE_BASE: Record<string, ModelKnowledge> = {
  'qwen2.5-coder': {
    tag: 'qwen2.5-coder',
    displayName: 'Qwen 2.5 Coder',
    family: 'Qwen',
    author: 'Alibaba Cloud Intelligence',
    license: 'Apache 2.0 (Commercial OK)',
    contextWindow: '128,000 tokens (128k)',
    specialtyHeadline: 'Premier agentic coding, automated terminal workflows & reliable tool calling',
    bestFor: [
      'Autonomous multi-step tool calling, file modifications, and CLI terminal automation',
      'Writing, debugging, and refactoring Python, JavaScript/TypeScript, SQL, and Go',
      'Small business workflow scripts, spreadsheet automation, and API connectors',
      'Extracting structured JSON schema records from raw emails, PDFs, and invoices',
    ],
    strengths: [
      'State-of-the-art 92%+ score on HumanEval & EvalPlus coding benchmarks',
      '128k context window handles full multi-file codebases in a single prompt',
      'Exceptional adherence to JSON function calling schemas without hallucinating params',
    ],
    considerations: [
      '7B model requires 6GB VRAM for smooth GPU offload; 14B requires 12GB+ VRAM',
      'Reasoning steps are concise and direct, but can be verbose on complex architectural problems',
    ],
    scores: {
      coding: 98,
      toolCalling: 96,
      reasoning: 90,
      speed: 86,
    },
    keyTags: ['Coding 98%', 'Tool Automation', 'Terminal Scripts', '128k Context'],
  },
  'llama3.2': {
    tag: 'llama3.2',
    displayName: 'Llama 3.2',
    family: 'Llama',
    author: 'Meta AI',
    license: 'Llama 3.2 Community',
    contextWindow: '128,000 tokens (128k)',
    specialtyHeadline: 'Ultra-low latency conversational assistant for everyday desktop productivity',
    bestFor: [
      'Instant conversational replies with near-zero latency (<25ms TTFT)',
      'Drafting business emails, customer support tickets, and executive summaries',
      'Running on laptops and lightweight PCs with modest or shared memory',
      'Quick copy editing, tone adjustment, and real-time brainstorming',
    ],
    strengths: [
      'Tiny memory footprint (~2.0 GB), leaving your GPU free for multitasking',
      'Warm, natural, and polite conversational tone aligned by Meta AI',
      'Supports full 128k context length despite its compact 3B parameter size',
    ],
    considerations: [
      '3B parameters may miss subtle edge-case logic in large multi-file software refactorings',
      'Simpler function calling schema adherence compared to specialized coder models',
    ],
    scores: {
      coding: 72,
      toolCalling: 80,
      reasoning: 78,
      speed: 99,
    },
    keyTags: ['Instant Latency', 'Low Memory (~2GB)', 'Email & Chat', '128k Context'],
  },
  'llama3.1': {
    tag: 'llama3.1',
    displayName: 'Llama 3.1',
    family: 'Llama',
    author: 'Meta AI',
    license: 'Llama 3.1 Community',
    contextWindow: '128,000 tokens (128k)',
    specialtyHeadline: 'Enterprise-grade open foundation model with broad versatile knowledge',
    bestFor: [
      'Deep document analysis, policy synthesis, and strategic business planning',
      'Complex multi-turn customer communication and nuanced sentiment evaluation',
      'General problem solving with high factual accuracy and safety compliance',
      'Reliable tool calling and structured function invocation across diverse domains',
    ],
    strengths: [
      'Extensively pretrained on 15+ trillion tokens by Meta',
      'Proven production reliability across global enterprise workloads',
      'Rock-solid 128k context retention and multi-lingual fluency',
    ],
    considerations: [
      '8B model needs at least 6-8GB VRAM for full GPU inference speed',
      'Larger on-disk download (~4.9 GB) compared to Llama 3.2',
    ],
    scores: {
      coding: 84,
      toolCalling: 88,
      reasoning: 88,
      speed: 80,
    },
    keyTags: ['Enterprise Grade', 'Versatile Generalist', 'Document Analysis', '128k Context'],
  },
  'deepseek-r1': {
    tag: 'deepseek-r1',
    displayName: 'DeepSeek R1',
    family: 'DeepSeek',
    author: 'DeepSeek-AI',
    license: 'MIT (Fully Open Commercial)',
    contextWindow: '64,000 tokens (64k)',
    specialtyHeadline: 'Chain-of-thought mathematical reasoning, logic puzzles & algorithmic proofs',
    bestFor: [
      'Solving complex mathematical proofs, financial algorithms, and logic puzzles',
      'Root-cause diagnosis of complex software architecture bugs',
      'Multi-step deductive reasoning where intermediate thinking must be validated',
      'Formal academic, scientific, and technical analysis',
    ],
    strengths: [
      'Outputs internal thinking traces (<think>...</think>) before presenting its answer',
      'Achieves parity with closed frontier models (like OpenAI o1) on math benchmarks',
      'Completely permissive MIT license allows unrestricted commercial deployment',
    ],
    considerations: [
      'Does NOT support standard JSON tool calling or function invocation schemas',
      'Response time is slower because it generates detailed thinking tokens first',
    ],
    scores: {
      coding: 88,
      toolCalling: 35,
      reasoning: 99,
      speed: 65,
    },
    keyTags: ['Chain-of-Thought', 'Math & Logic 99%', 'Internal Thinking', 'MIT License'],
  },
  'phi4': {
    tag: 'phi4',
    displayName: 'Phi-4',
    family: 'Phi',
    author: 'Microsoft Research',
    license: 'MIT (Commercial OK)',
    contextWindow: '16,000 tokens (16k)',
    specialtyHeadline: 'High-efficiency reasoning & STEM problem solving trained on synthetic data',
    bestFor: [
      'Mathematical reasoning and physics/chemistry STEM problem analysis',
      'Instruction following and logical deduction within a tight memory budget',
      'Edge devices, developer laptops, and local small business servers',
      'Fast algorithmic question answering and logic checks',
    ],
    strengths: [
      'Phi-4 Mini (3.8B) punches far above its weight, beating many older 7B/8B models',
      'Fast generation speed and modest VRAM requirements (3-4GB)',
      'Trained on Microsoft’s curated synthetic textbooks and reasoning datasets',
    ],
    considerations: [
      'Context window is 16k tokens (smaller than Llama’s 128k)',
      'Strictly English-optimized; weaker on non-English idioms',
    ],
    scores: {
      coding: 83,
      toolCalling: 76,
      reasoning: 93,
      speed: 92,
    },
    keyTags: ['High Efficiency', 'STEM & Math', 'Microsoft Research', 'MIT License'],
  },
  'mistral': {
    tag: 'mistral',
    displayName: 'Mistral 7B',
    family: 'Mistral',
    author: 'Mistral AI',
    license: 'Apache 2.0',
    contextWindow: '32,000 tokens (32k)',
    specialtyHeadline: 'Fluid European open generalist with natural language finesse and multilingual mastery',
    bestFor: [
      'Creative business copywriting, press releases, and marketing campaigns',
      'Multilingual translations (French, German, Spanish, Italian, English)',
      'Customer correspondence, sales outreach emails, and document summaries',
      'Fast, conversational brainstorming and customer interaction',
    ],
    strengths: [
      'Remarkably fluid and pleasant conversational tone',
      'Sliding window attention for efficient memory utilization during inference',
      'Proven production reliability across European enterprise businesses',
    ],
    considerations: [
      'Coding depth is good for general scripts, but specialized coder models edge it out on tools',
      'Requires ~6GB VRAM for 7B version',
    ],
    scores: {
      coding: 80,
      toolCalling: 82,
      reasoning: 85,
      speed: 84,
    },
    keyTags: ['Multilingual', 'Business Writing', 'European AI', 'Apache 2.0'],
  },
  'qwen3': {
    tag: 'qwen3',
    displayName: 'Qwen 3 / Qwen 2.5',
    family: 'Qwen',
    author: 'Alibaba Cloud Intelligence',
    license: 'Apache 2.0',
    contextWindow: '128,000 tokens (128k)',
    specialtyHeadline: 'Versatile multilingual generalist with state-of-the-art instruction following',
    bestFor: [
      'Comprehensive business workflow automation and agent task delegation',
      'Complex structured table parsing, accounting data, and multilingual translation',
      'High-context multi-turn conversational advisory',
      'Multi-step planning and cross-lingual comprehension across 30+ languages',
    ],
    strengths: [
      'Broad multilingual pretraining dataset with superior non-English comprehension',
      'Exceptional tool calling and agent capability across diverse domains',
      'Full 128k context window support',
    ],
    considerations: [
      'Requires 6-8GB VRAM for comfortable GPU offloading of 7B/8B models',
    ],
    scores: {
      coding: 91,
      toolCalling: 94,
      reasoning: 92,
      speed: 82,
    },
    keyTags: ['Multilingual 30+', 'Autonomous Agents', '128k Context', 'Apache 2.0'],
  },
  'gemma2': {
    tag: 'gemma2',
    displayName: 'Gemma 2',
    family: 'Gemma',
    author: 'Google DeepMind',
    license: 'Gemma Terms of Use',
    contextWindow: '8,192 tokens (8k)',
    specialtyHeadline: 'Google DeepMind’s distilled architectural precision with high factual accuracy',
    bestFor: [
      'Factual question answering, research synthesis, and educational tutoring',
      'Text summarization and nuanced sentiment classification',
      'High-precision information retrieval without embellishment',
    ],
    strengths: [
      'Pioneering architecture with interleaved local-global attention layers',
      'Trained on rich Google knowledge distillation corpus for superior MMLU scores',
      '2B variant is exceptionally fast on portable laptops and edge devices',
    ],
    considerations: [
      '8k context window is tighter than Llama’s 128k',
      'Tool calling format differs slightly from standard OpenAI JSON schema',
    ],
    scores: {
      coding: 78,
      toolCalling: 72,
      reasoning: 87,
      speed: 89,
    },
    keyTags: ['Google DeepMind', 'Factual Accuracy', 'Lightweight 2B', 'High Precision'],
  },
};

export function getModelKnowledge(tagOrName: string): ModelKnowledge {
  const norm = (tagOrName || '').toLowerCase().trim();

  // 1. Qwen Coder variants
  if (norm.includes('qwen') && (norm.includes('coder') || norm.includes('code'))) {
    const is14b = norm.includes('14b');
    const is3b = norm.includes('3b');
    const is1b = norm.includes('1.5b') || norm.includes('1b');
    const base = MODEL_KNOWLEDGE_BASE['qwen2.5-coder'];
    return {
      ...base,
      tag: tagOrName,
      displayName: is14b
        ? 'Qwen 2.5 Coder 14B (Pro Workstation)'
        : is3b
        ? 'Qwen 2.5 Coder 3B (Fast Edge)'
        : is1b
        ? 'Qwen 2.5 Coder 1.5B (Ultra-Light)'
        : 'Qwen 2.5 Coder 7B (Premier)',
    };
  }

  // 2. Llama 3.2
  if (norm.includes('llama3.2') || norm.includes('llama-3.2')) {
    const is1b = norm.includes('1b');
    const base = MODEL_KNOWLEDGE_BASE['llama3.2'];
    return {
      ...base,
      tag: tagOrName,
      displayName: is1b ? 'Llama 3.2 1B (Ultra-Light)' : 'Llama 3.2 3B (Fast Chat)',
    };
  }

  // 3. Llama 3.1
  if (norm.includes('llama3.1') || norm.includes('llama-3.1') || (norm.includes('llama3') && !norm.includes('3.2'))) {
    const is70b = norm.includes('70b');
    const base = MODEL_KNOWLEDGE_BASE['llama3.1'];
    return {
      ...base,
      tag: tagOrName,
      displayName: is70b ? 'Llama 3.1 70B (Enterprise Large)' : 'Llama 3.1 8B (Enterprise Standard)',
    };
  }

  // 4. DeepSeek R1
  if (norm.includes('deepseek') || norm.includes('r1')) {
    const is14b = norm.includes('14b');
    const is1b = norm.includes('1.5b');
    const base = MODEL_KNOWLEDGE_BASE['deepseek-r1'];
    return {
      ...base,
      tag: tagOrName,
      displayName: is14b
        ? 'DeepSeek R1 14B (Heavy Reasoning)'
        : is1b
        ? 'DeepSeek R1 1.5B (Edge Reasoning)'
        : 'DeepSeek R1 7B / 8B (Chain-of-Thought)',
    };
  }

  // 5. Phi 4
  if (norm.includes('phi4') || norm.includes('phi-4') || norm.includes('phi')) {
    const isMini = norm.includes('mini');
    const base = MODEL_KNOWLEDGE_BASE['phi4'];
    return {
      ...base,
      tag: tagOrName,
      displayName: isMini ? 'Phi-4 Mini 3.8B (Compact Logic)' : 'Phi-4 14B (Deep Logic)',
    };
  }

  // 6. Mistral / Codestral
  if (norm.includes('mistral') || norm.includes('codestral') || norm.includes('mixtral')) {
    const isCodestral = norm.includes('codestral');
    const base = MODEL_KNOWLEDGE_BASE['mistral'];
    return {
      ...base,
      tag: tagOrName,
      displayName: isCodestral ? 'Codestral 22B (Code Specialist)' : 'Mistral 7B (Fluent Generalist)',
      scores: isCodestral ? { coding: 95, toolCalling: 90, reasoning: 88, speed: 75 } : base.scores,
    };
  }

  // 7. Qwen general
  if (norm.includes('qwen')) {
    const base = MODEL_KNOWLEDGE_BASE['qwen3'];
    return {
      ...base,
      tag: tagOrName,
      displayName: norm.includes('3') ? 'Qwen 3 (Multilingual)' : 'Qwen 2.5 (Multilingual)',
    };
  }

  // 8. Gemma 2
  if (norm.includes('gemma')) {
    const base = MODEL_KNOWLEDGE_BASE['gemma2'];
    return {
      ...base,
      tag: tagOrName,
      displayName: norm.includes('2b') ? 'Gemma 2 2B (Ultra-Light)' : 'Gemma 2 9B (High Precision)',
    };
  }

  // 9. Dynamic Fallback for Any Custom Model
  const isCode = norm.includes('code') || norm.includes('coder') || norm.includes('dev');
  const isReasoning = norm.includes('math') || norm.includes('think') || norm.includes('reason');
  const isSmall = norm.includes('1b') || norm.includes('2b') || norm.includes('3b') || norm.includes('mini') || norm.includes('tiny');
  const isLarge = norm.includes('14b') || norm.includes('32b') || norm.includes('70b');

  return {
    tag: tagOrName,
    displayName: tagOrName.charAt(0).toUpperCase() + tagOrName.slice(1),
    family: 'Custom / Community',
    author: 'Open Source Community',
    license: 'Open Model Weights',
    contextWindow: isSmall ? '8k - 32k tokens' : '32k - 128k tokens',
    specialtyHeadline: isCode
      ? 'Specialized open coding model for scripts and software tasks'
      : isReasoning
      ? 'Analytical problem solving with logical deduction'
      : isSmall
      ? 'Compact low-latency model optimized for edge devices'
      : 'General purpose open language model for private local inference',
    bestFor: isCode
      ? [
          'Code generation, debugging, and terminal automation',
          'Small business workflow scripts and API integration',
          'Structured JSON extraction from text',
        ]
      : [
          'Private on-premise business chat and confidential document review',
          'Summarization, drafting customer communications, and brainstorming',
          'Local offline execution with 100% data privacy and zero cloud telemetry',
        ],
    strengths: [
      'Runs 100% offline and locally on your hardware with zero telemetry',
      'No API subscription fees or external network dependency',
      isSmall ? 'Low RAM usage and quick boot times' : 'Deep parameter representation',
    ],
    considerations: [
      isLarge
        ? 'Large parameter size requires substantial VRAM/RAM'
        : 'Verify parameter capability against specialized enterprise benchmarks',
    ],
    scores: {
      coding: isCode ? 90 : 75,
      toolCalling: isCode ? 88 : 72,
      reasoning: isReasoning ? 94 : 78,
      speed: isSmall ? 95 : isLarge ? 65 : 82,
    },
    keyTags: [
      'Private Local',
      isCode ? 'Code Specialist' : 'General Chat',
      isSmall ? 'Low Memory' : 'Deep Weights',
      'Offline',
    ],
  };
}

export interface ArchitectureModelPreset {
  id: string;
  name: string;
  tag: string;
  family: string;
  category: 'code' | 'fast' | 'reasoning' | 'general' | 'pro';
  categoryLabel: string;
  sizeGb: number;
  minVramGb: number;
  minRamGb: number;
  description: string;
  toolsSupported: boolean;
  highlight?: string;
}

export const ARCHITECTURE_RECOMMENDED_MODELS: ArchitectureModelPreset[] = [
  {
    id: 'qwen2.5-coder-7b',
    name: 'Qwen 2.5 Coder 7B',
    tag: 'qwen2.5-coder:7b',
    family: 'Qwen',
    category: 'code',
    categoryLabel: 'Code & Tool Automation',
    sizeGb: 4.7,
    minVramGb: 6,
    minRamGb: 8,
    description: 'Premier agentic model with state-of-the-art function calling, terminal command execution, and coding precision.',
    toolsSupported: true,
    highlight: 'Best for Tools & Workflows',
  },
  {
    id: 'llama-3.2-3b',
    name: 'Llama 3.2 3B',
    tag: 'llama3.2:3b',
    family: 'Llama',
    category: 'fast',
    categoryLabel: 'Fast & Everyday Chat',
    sizeGb: 2.0,
    minVramGb: 3,
    minRamGb: 6,
    description: 'Ultra-lightweight conversational model from Meta. Fits practically any modern GPU or laptop with blazing latency.',
    toolsSupported: true,
    highlight: 'Lowest Latency & Memory',
  },
  {
    id: 'qwen-3-8b',
    name: 'Qwen 3 8B',
    tag: 'qwen3:8b',
    family: 'Qwen',
    category: 'reasoning',
    categoryLabel: 'Deep Reasoning & Instruction',
    sizeGb: 5.2,
    minVramGb: 8,
    minRamGb: 12,
    description: 'Top-tier generalist with superior reasoning, multi-step problem solving, and reliable tool calling.',
    toolsSupported: true,
    highlight: 'Versatile Coworker',
  },
  {
    id: 'deepseek-r1-7b',
    name: 'DeepSeek R1 7B',
    tag: 'deepseek-r1:7b',
    family: 'DeepSeek',
    category: 'reasoning',
    categoryLabel: 'Chain-of-Thought Reasoning',
    sizeGb: 4.7,
    minVramGb: 6,
    minRamGb: 10,
    description: 'Open reasoning model that outputs internal thinking traces before delivering verified math and logic answers.',
    toolsSupported: false,
    highlight: 'Deep Mathematical & Logic',
  },
  {
    id: 'phi-4-mini',
    name: 'Phi-4 Mini 3.8B',
    tag: 'phi4-mini',
    family: 'Phi',
    category: 'fast',
    categoryLabel: 'Compact Logic & Math',
    sizeGb: 2.5,
    minVramGb: 4,
    minRamGb: 8,
    description: 'Microsoft’s high-efficiency reasoning model specializing in mathematical rigor and compact instruction execution.',
    toolsSupported: true,
    highlight: 'High Efficiency',
  },
  {
    id: 'qwen2.5-coder-14b',
    name: 'Qwen 2.5 Coder 14B',
    tag: 'qwen2.5-coder:14b',
    family: 'Qwen',
    category: 'pro',
    categoryLabel: 'Heavyweight Workstation Pro',
    sizeGb: 9.0,
    minVramGb: 12,
    minRamGb: 16,
    description: 'Pro workstation model for deep architectural design, complex refactoring, and multi-file codebases.',
    toolsSupported: true,
    highlight: 'Pro Grade (12GB+ VRAM)',
  },
  {
    id: 'mistral-7b',
    name: 'Mistral 7B',
    tag: 'mistral:7b',
    family: 'Mistral',
    category: 'general',
    categoryLabel: 'Balanced Generalist',
    sizeGb: 4.1,
    minVramGb: 6,
    minRamGb: 8,
    description: 'Dependable open model with natural writing fluency, summarization, and customer communication skills.',
    toolsSupported: true,
    highlight: 'Creative & Business Writing',
  },
];

export interface FamilyVariant {
  tag: string;
  sizeGb: number;
  label: string;
}

export interface ModelFamily {
  id: string;
  name: string;
  variants: FamilyVariant[];
}

export const POPULAR_FAMILIES: ModelFamily[] = [
  {
    id: 'qwen',
    name: 'Qwen 2.5 Coder',
    variants: [
      { tag: 'qwen2.5-coder:1.5b', sizeGb: 1.0, label: '1.5B' },
      { tag: 'qwen2.5-coder:3b', sizeGb: 2.0, label: '3B' },
      { tag: 'qwen2.5-coder:7b', sizeGb: 4.7, label: '7B' },
      { tag: 'qwen2.5-coder:14b', sizeGb: 9.0, label: '14B' },
    ],
  },
  {
    id: 'llama',
    name: 'Llama 3.2',
    variants: [
      { tag: 'llama3.2:1b', sizeGb: 1.3, label: '1B' },
      { tag: 'llama3.2:3b', sizeGb: 2.0, label: '3B' },
    ],
  },
  {
    id: 'deepseek',
    name: 'DeepSeek R1',
    variants: [
      { tag: 'deepseek-r1:1.5b', sizeGb: 1.1, label: '1.5B' },
      { tag: 'deepseek-r1:7b', sizeGb: 4.7, label: '7B' },
      { tag: 'deepseek-r1:8b', sizeGb: 5.2, label: '8B' },
      { tag: 'deepseek-r1:14b', sizeGb: 9.0, label: '14B' },
    ],
  },
  {
    id: 'mistral',
    name: 'Mistral',
    variants: [
      { tag: 'mistral:7b', sizeGb: 4.1, label: '7B' },
    ],
  },
  {
    id: 'phi',
    name: 'Phi-4',
    variants: [
      { tag: 'phi4-mini', sizeGb: 2.5, label: 'Mini' },
      { tag: 'phi4', sizeGb: 9.1, label: '14B' },
    ],
  },
];

export function getArchitectureFit(
  sizeGb: number,
  hw?: ModelRecommendations['hardware']
): { fit: 'fits_gpu' | 'slow' | 'too_big'; label: string; badgeClass: string; icon: string } {
  if (!hw) {
    return {
      fit: 'slow',
      label: 'Hardware detection pending',
      badgeClass: 'bg-slate-800 text-slate-300 border-slate-700',
      icon: '❓',
    };
  }
  const vramGb = (hw.vramBytes || 0) / (1024 * 1024 * 1024);
  const ramGb = (hw.ramBytes || 0) / (1024 * 1024 * 1024);
  const requiredGb = sizeGb * 1.15;

  if (vramGb > 0 && requiredGb <= vramGb) {
    return {
      fit: 'fits_gpu',
      label: `Fits GPU VRAM (${vramGb.toFixed(1)} GB Available) — Fast`,
      badgeClass: 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60',
      icon: '⚡',
    };
  }
  if (requiredGb <= vramGb + ramGb * 0.5) {
    return {
      fit: 'slow',
      label: `Spills into System RAM (${ramGb.toFixed(1)} GB RAM) — Slower`,
      badgeClass: 'bg-amber-950/80 text-amber-300 border-amber-700/60',
      icon: '⚠️',
    };
  }
  return {
    fit: 'too_big',
    label: `Exceeds Memory Capacity (~${requiredGb.toFixed(1)} GB needed)`,
    badgeClass: 'bg-rose-950/80 text-rose-300 border-rose-700/60',
    icon: '❌',
  };
}
