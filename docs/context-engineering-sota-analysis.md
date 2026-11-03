# State-of-the-Art Context Engineering Analysis

## Executive Summary

This document analyzes state-of-the-art context management techniques from leading AI coding agents (Claude Code, Aider, GitHub Copilot) and proposes a SOLID/DRY-compliant architecture for implementing advanced context engineering in Emiliano.

**Current Status:** ✅ Basic token-aware truncation implemented
**Gap Analysis:** 10 major techniques missing from state-of-the-art
**Proposed:** Modular, extensible architecture following SOLID principles

---

## State-of-the-Art Analysis

### 1. Claude Code (Anthropic)

**Context Window:** 200,000 tokens

**Key Techniques:**

| Technique | Description | Implementation |
|:---|:---|:---|
| **Hierarchical Priority** | file content > conversation history > path rules | Drops low-priority items first |
| **Automatic Compaction** | Summarizes old conversation when approaching limit | Uses LLM to generate summaries |
| **Manual Summarization** | `/compact` command for user-triggered compression | On-demand summary generation |
| **Persistent Context** | `CLAUDE.md` files never compressed | Read at session start, preserved |
| **Usage Visibility** | `/context` command shows token breakdown | Real-time metrics display |
| **Complete History** | Full conversation + files + tool results in every turn | No truncation until limit |

**Sources:**
- [Claude Code Context Window Management in 2026](https://dev.to/jsmanifest/claude-code-context-window-management-in-2026-what-gets-included-what-gets-dropped-and-how-to-26kh)
- [Understanding Claude Code's /context command](https://dannywillems.github.io/2026/01/16/claude-code-context-command.html)
- [Managing Claude Code's Context: a practical handbook](https://www.cometapi.com/managing-claude-codes-context/)

---

### 2. Aider (Open Source)

**Context Window:** Model-dependent

**Key Techniques:**

| Technique | Description | Implementation |
|:---|:---|:---|
| **Repository Map** | File structure + symbols (no content), 1K tokens | AST extraction, optimized selection |
| **Relevance-Based Optimization** | Map optimized based on chat history + active files | Dynamic relevance scoring |
| **Context Caching** | System prompt, repo map, files cached provider-side | Structured for provider caching |
| **Chat History Summarization** | Auto-summarize at 8K token limit | Configurable threshold |
| **Token Budgets** | Separate budgets: repo map (1K), history (8K) | Isolated allocation per component |
| **Task Isolation** | `/clear` between unrelated tasks | Prevents context pollution |

**Sources:**
- [Repository map](https://aider.chat/docs/repomap.html)
- [How to Manage Aider Token Limits and Context Windows](https://fast.io/resources/aider-token-limit/)
- [Understanding AI Coding Agents Through Aider's Architecture](https://simranchawla.com/understanding-ai-coding-agents-through-aiders-architecture/)

---

### 3. GitHub Copilot (Microsoft + OpenAI)

**Context Window:** 8K-32K tokens (model-dependent)

**Key Techniques:**

| Technique | Description | Implementation |
|:---|:---|:---|
| **Neighboring Tabs** | All open IDE files, not just active file | Multi-file context gathering |
| **Fill-In-the-Middle (FIM)** | Code before + after cursor | Bidirectional context |
| **Semantic Retrieval** | Vector DB + embeddings for relevant code | Similarity search |
| **Prompt Library** | Pre-engineered prompts with prioritization | ML-based selection |
| **Real-Time Filtering** | Dynamic context element selection | Fit within token limits |
| **Matching Algorithm** | Find similar code in open files | Code similarity detection |

**Sources:**
- [How GitHub Copilot is getting better at understanding your code](https://github.blog/ai-and-ml/github-copilot/how-github-copilot-is-getting-better-at-understanding-your-code/)
- [Improving GitHub Copilot's Contextual Understanding Through Advanced Prompt Engineering and Retrieval](https://www.zenml.io/llmops-database/improving-github-copilot-s-contextual-understanding-through-advanced-prompt-engineering-and-retrieval)
- [How GitHub Copilot Handles Multi-File Context Internally](https://dzone.com/articles/github-copilot-multi-file-context-internal-architecture)

---

### 4. Advanced Techniques from Research (2025)

**Recursive Summarization:**
- Partition conversations into chunks
- Generate local summaries
- Hierarchically merge summaries
- LLM-Resumé method: LLM updates its own memory

**AST-Based Repository Analysis:**
- Tree-sitter for multi-language parsing
- Extract classes, methods, relationships
- Build structural index (nodes + edges)
- Linearization strategies (pre-order, SBT, path decomposition)

**Sources:**
- [Recursively Summarizing Enables Long-Term Dialogue Memory in Large Language Models](https://arxiv.org/pdf/2308.15022)
- [AstraAI: LLMs, Retrieval, and AST-Guided Assistance for HPC Codebases](https://arxiv.org/pdf/2603.27423)
- [SaraCoder: Orchestrating Semantic and Structural Cues for Repository-Level Code Completion](https://arxiv.org/pdf/2508.10068)

---

## Gap Analysis: What Emiliano is Missing

### ✅ Currently Implemented
1. Token counting (tiktoken)
2. Model-specific context limits
3. Sliding window truncation
4. System message preservation
5. Configurable truncation strategies

### ❌ Missing from State-of-the-Art

| Priority | Technique | Impact | Complexity |
|:---|:---|:---|:---|
| **P0** | Conversation Summarization | High | Medium |
| **P0** | Context Usage Metrics/Visualization | High | Low |
| **P0** | Persistent Context Files | High | Low |
| **P1** | Repository Map (Structure) | Very High | High |
| **P1** | Multi-File Context Awareness | Very High | Medium |
| **P1** | Context Caching | High | Medium |
| **P2** | Semantic Code Retrieval (Vector DB) | Very High | High |
| **P2** | Hierarchical Context Priority | Medium | Medium |
| **P2** | Task-Based Context Isolation | Medium | Low |
| **P3** | Fill-In-the-Middle Support | Medium | High |

---

## SOLID/DRY Architecture Design

### Design Principles Applied

#### 1. Single Responsibility Principle (SRP)
Each component has ONE reason to change:
- `ContextWindowManager` → Token counting + truncation
- `ConversationSummarizer` → History summarization
- `RepositoryMapper` → Code structure extraction
- `ContextCache` → Provider-side caching
- `SemanticRetriever` → Vector search

#### 2. Open/Closed Principle (OCP)
Extend behavior without modifying existing code:
- Abstract `ContextProvider` interface
- Pluggable summarization strategies
- Extensible retrieval backends

#### 3. Liskov Substitution Principle (LSP)
Any context provider can replace another:
- All providers implement `ContextProvider` protocol
- Uniform interface for context retrieval

#### 4. Interface Segregation Principle (ISP)
Clients depend only on methods they use:
- `ITokenCounter` → count_tokens()
- `ITruncator` → truncate()
- `ISummarizer` → summarize()
- `IRetriever` → retrieve()

#### 5. Dependency Inversion Principle (DIP)
Depend on abstractions, not concretions:
- Dispatcher depends on `IContextManager` interface
- Context manager depends on `ISummarizer` interface
- No direct dependencies on implementations

#### DRY (Don't Repeat Yourself)
- Shared token counting logic
- Reusable context formatting
- Common configuration management
- Unified logging/metrics

---

## Proposed Architecture

### Component Hierarchy

```
emiliano/core/context/
├── __init__.py
├── base.py                     # Interfaces/protocols (IContextProvider, ISummarizer, etc.)
├── manager.py                  # ContextWindowManager (existing, refactored)
├── summarization/
│   ├── __init__.py
│   ├── base.py                 # ISummarizer protocol
│   ├── recursive.py            # RecursiveSummarizer
│   ├── hierarchical.py         # HierarchicalSummarizer
│   └── simple.py               # SimpleTruncator (fallback)
├── repository/
│   ├── __init__.py
│   ├── base.py                 # IRepositoryMapper protocol
│   ├── mapper.py               # RepositoryMapper
│   ├── ast_extractor.py        # ASTExtractor (tree-sitter)
│   └── structure_index.py      # StructureIndex (graph of symbols)
├── retrieval/
│   ├── __init__.py
│   ├── base.py                 # ISemanticRetriever protocol
│   ├── vector_store.py         # VectorStore (embeddings)
│   ├── similarity.py           # CodeSimilarityMatcher
│   └── ranking.py              # RelevanceRanker
├── cache/
│   ├── __init__.py
│   ├── base.py                 # IContextCache protocol
│   ├── provider_cache.py       # ProviderCache (Anthropic/OpenAI caching)
│   └── local_cache.py          # LocalCache (disk/redis)
├── metrics/
│   ├── __init__.py
│   ├── collector.py            # MetricsCollector
│   └── visualizer.py           # ContextVisualizer (/context command)
└── persistent/
    ├── __init__.py
    ├── loader.py               # PersistentContextLoader (CLAUDE.md style)
    └── storage.py              # ConversationStorage (SQLite)
```

### Key Interfaces (base.py)

```python
from typing import Protocol, List, Dict, Optional, Tuple
from abc import abstractmethod

class ITokenCounter(Protocol):
    """Token counting interface."""
    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

class ISummarizer(Protocol):
    """Conversation summarization interface."""
    @abstractmethod
    async def summarize(
        self,
        messages: List[Dict[str, str]],
        max_output_tokens: int = 500
    ) -> Dict[str, str]: ...

class IRepositoryMapper(Protocol):
    """Repository structure mapping interface."""
    @abstractmethod
    async def build_map(
        self,
        repo_path: str,
        budget_tokens: int = 1000
    ) -> str: ...

    @abstractmethod
    def update_relevance(
        self,
        query: str,
        history: List[Dict[str, str]]
    ) -> None: ...

class ISemanticRetriever(Protocol):
    """Semantic code retrieval interface."""
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict] = None
    ) -> List[Tuple[str, float]]: ...

class IContextCache(Protocol):
    """Context caching interface."""
    @abstractmethod
    async def store(
        self,
        key: str,
        content: str,
        ttl: Optional[int] = None
    ) -> str: ...

    @abstractmethod
    async def retrieve(self, key: str) -> Optional[str]: ...

class IContextProvider(Protocol):
    """Unified context provider interface."""
    @abstractmethod
    async def get_context(
        self,
        query: str,
        history: List[Dict[str, str]],
        budget_tokens: int
    ) -> Dict[str, any]: ...
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
**Priority: P0 - Critical for Long Conversations**

#### 1.1 Conversation Summarization
- [ ] Create `emiliano/core/context/summarization/` module
- [ ] Implement `RecursiveSummarizer` (LLM-based)
- [ ] Add configuration: `context.summarization.enabled`, `context.summarization.threshold`
- [ ] Integrate into `ContextWindowManager`
- [ ] Add tests for summarization

**Deliverable:** Conversations automatically summarized instead of truncated

#### 1.2 Context Metrics & Visualization
- [ ] Create `emiliano/core/context/metrics/` module
- [ ] Implement `MetricsCollector` (token usage tracking)
- [ ] Add `/context` command to CLI
- [ ] Display: total tokens, by component (history, files, repo map)
- [ ] Add logging for context events

**Deliverable:** `/context` command shows token breakdown

#### 1.3 Persistent Context Files
- [ ] Create `emiliano/core/context/persistent/` module
- [ ] Implement `PersistentContextLoader` (reads EMILIANO.md)
- [ ] Auto-load on session start
- [ ] Never compress/truncate persistent files
- [ ] Document in user guide

**Deliverable:** `EMILIANO.md` files for persistent instructions

**SOLID Compliance:**
- SRP: Each component handles one concern
- OCP: Pluggable summarization strategies
- DIP: Dispatcher depends on `ISummarizer` interface

**Files to Modify:**
- `packages/engine/emiliano/core/context_manager.py` → Refactor to use ISummarizer
- `packages/engine/emiliano/cli.py` → Add `/context` command
- `packages/engine/emiliano/core/config.py` → Add summarization config

---

### Phase 2: Repository Intelligence (Week 3-5)
**Priority: P1 - Essential for Multi-File Context**

#### 2.1 Repository Mapper
- [ ] Create `emiliano/core/context/repository/` module
- [ ] Integrate tree-sitter for AST parsing
- [ ] Implement `ASTExtractor` (extract classes, functions, symbols)
- [ ] Implement `RepositoryMapper` (build structure map)
- [ ] Add relevance scoring (based on query + history)
- [ ] Budget: 1K tokens default

**Deliverable:** Auto-generated repo map in context

#### 2.2 Multi-File Context Awareness
- [ ] Track files mentioned in conversation
- [ ] Track files modified by tools
- [ ] Build dependency graph (imports, calls)
- [ ] Auto-include related files in context
- [ ] Prioritize by recency + relevance

**Deliverable:** Related files automatically included

#### 2.3 Context Caching
- [ ] Create `emiliano/core/context/cache/` module
- [ ] Implement `ProviderCache` (Anthropic prompt caching)
- [ ] Structure context for optimal caching (system → repo map → files → history)
- [ ] Add cache hit metrics
- [ ] Document cost savings

**Deliverable:** 90% cost reduction via caching

**SOLID Compliance:**
- SRP: Mapper, extractor, cache are separate
- ISP: `IRepositoryMapper` and `IContextCache` interfaces
- OCP: Pluggable AST extractors (tree-sitter, babel, etc.)

**Dependencies:**
- `tree-sitter>=0.20.0`
- `tree-sitter-python>=0.20.0`
- `tree-sitter-javascript>=0.20.0`

---

### Phase 3: Semantic Intelligence (Week 6-8)
**Priority: P2 - Advanced Features**

#### 3.1 Semantic Code Retrieval
- [ ] Create `emiliano/core/context/retrieval/` module
- [ ] Implement `VectorStore` (ChromaDB or FAISS)
- [ ] Generate embeddings for code chunks
- [ ] Implement `CodeSimilarityMatcher`
- [ ] Implement `RelevanceRanker`
- [ ] Add retrieval to context pipeline

**Deliverable:** Semantic search for relevant code

#### 3.2 Hierarchical Context Priority
- [ ] Define priority levels: P0 (persistent) → P1 (active files) → P2 (repo map) → P3 (history)
- [ ] Implement priority-based allocation
- [ ] Drop lower priority items first
- [ ] Add configuration per priority level

**Deliverable:** Intelligent context prioritization

#### 3.3 Task-Based Context Isolation
- [ ] Detect task switches (topic change detection)
- [ ] Suggest `/clear` when task changes
- [ ] Auto-partition context by task
- [ ] Save task history separately

**Deliverable:** Context doesn't pollute across tasks

**SOLID Compliance:**
- DIP: Dispatcher depends on `ISemanticRetriever` interface
- OCP: Pluggable vector stores (Chroma, FAISS, Pinecone)
- LSP: Any retriever can substitute another

**Dependencies:**
- `chromadb>=0.4.0` or `faiss-cpu>=1.7.0`
- `sentence-transformers>=2.2.0`

---

### Phase 4: Advanced Optimizations (Week 9-12)
**Priority: P3 - Nice to Have**

#### 4.1 Fill-In-the-Middle Support
- [ ] Implement FIM prompt formatting
- [ ] Extract code before + after cursor position
- [ ] Add FIM-aware models (Codex, StarCoder)
- [ ] Integrate with code completion

**Deliverable:** Better code completion context

#### 4.2 Conversation Storage & Recovery
- [ ] Implement `ConversationStorage` (SQLite)
- [ ] Save full history after each turn
- [ ] Add `/resume <session_id>` command
- [ ] Add `/sessions` command (list saved sessions)
- [ ] Add conversation search

**Deliverable:** Never lose conversation history

#### 4.3 Unified Blackboard (Future Horizons)
- [ ] Design shared memory layer
- [ ] Cross-harness context exchange
- [ ] Vector memory layer
- [ ] Implement blackboard protocol

**Deliverable:** Context shared across harnesses

---

## Configuration Schema

```yaml
# emiliano.yaml
context:
  # Basic truncation (Phase 0 - DONE)
  enabled: true
  max_tokens: null
  truncation_strategy: "sliding_window"
  safety_margin: 0.85
  reserve_tokens: 2000

  # Summarization (Phase 1)
  summarization:
    enabled: true
    strategy: "recursive"  # "recursive" | "hierarchical" | "simple"
    threshold_tokens: 8000  # Summarize when history exceeds this
    max_summary_tokens: 500

  # Persistent context (Phase 1)
  persistent:
    enabled: true
    filenames: ["EMILIANO.md", "CLAUDE.md", ".emiliano/context.md"]

  # Repository map (Phase 2)
  repository:
    enabled: true
    budget_tokens: 1000
    languages: ["python", "javascript", "typescript", "rust", "go"]
    max_depth: 5  # Directory traversal depth

  # Caching (Phase 2)
  cache:
    enabled: true
    provider: "anthropic"  # "anthropic" | "openai" | "local"
    ttl: 3600  # 1 hour

  # Semantic retrieval (Phase 3)
  retrieval:
    enabled: false  # Opt-in
    backend: "chromadb"  # "chromadb" | "faiss"
    embedding_model: "all-MiniLM-L6-v2"
    top_k: 5

  # Hierarchical priority (Phase 3)
  priority:
    P0_persistent: 10000  # Always include
    P1_active_files: 50000
    P2_repo_map: 1000
    P3_history: null  # Fill remaining

  # Metrics (Phase 1)
  metrics:
    enabled: true
    log_truncation: true
    log_cache_hits: true
```

---

## SOLID Compliance Summary

| Principle | Implementation | Benefit |
|:---|:---|:---|
| **SRP** | Each module has single responsibility | Easy to test, maintain, understand |
| **OCP** | Plugin architecture for strategies | Add new summarizers without changing core |
| **LSP** | All context providers interchangeable | Swap implementations seamlessly |
| **ISP** | Small, focused interfaces | Components depend only on what they need |
| **DIP** | Depend on abstractions (protocols) | Decouple high-level from low-level |
| **DRY** | Shared utils, configs, logging | No repeated code across modules |

---

## Performance Considerations

### Token Budget Allocation (Phase 2+)

For a 180K token model (Claude):
- **Reserve for response:** 2,000 tokens (1%)
- **Safety margin:** 27,000 tokens unused (15%)
- **Available:** 151,000 tokens (84%)

Distribution:
- **Persistent context (P0):** 10,000 tokens (7%)
- **Active files (P1):** 80,000 tokens (53%)
- **Repository map (P2):** 1,000 tokens (1%)
- **Conversation history (P3):** 60,000 tokens (39%)

### Latency Impact

| Technique | Added Latency | Mitigation |
|:---|:---|:---|
| Summarization | +2-5s per call | Cache summaries, async generation |
| Repository map | +0.5-2s | Cache AST, incremental updates |
| Semantic retrieval | +0.1-0.5s | Index in background, use FAISS |
| Vector embedding | +0.2-1s | Batch embed, cache embeddings |

**Target:** <3s total overhead for context preparation

### Cost Optimization

- **Prompt caching:** 90% cost reduction (10x cheaper for cached tokens)
- **Summarization:** 70% token reduction (3x cheaper conversations)
- **Repository map:** Negligible (1K tokens vs 50K+ for full files)

**Estimated savings:** 85-95% cost reduction for long sessions

---

## Testing Strategy

### Unit Tests
- Each component has isolated tests
- Mock interfaces for dependencies
- Test edge cases (empty, oversized, malformed)

### Integration Tests
- Test component interactions
- Test full context pipeline
- Test with real LLM calls (using test API keys)

### Performance Tests
- Measure token counting speed
- Measure summarization latency
- Measure retrieval latency
- Load test with 1000+ message conversations

### User Acceptance Tests
- Long coding session (50+ messages)
- Multi-file refactoring task
- Task switching scenarios
- Context recovery after crash

---

## Migration Path

### For Existing Users

**Phase 1 (Backward Compatible):**
- Existing `context.*` config still works
- Summarization is opt-in (`context.summarization.enabled: false` by default)
- Truncation fallback if summarization fails

**Phase 2 (Default On):**
- Repository map enabled by default
- Can disable with `context.repository.enabled: false`

**Phase 3 (Opt-In Advanced):**
- Semantic retrieval requires explicit `context.retrieval.enabled: true`
- Requires additional dependencies

### Breaking Changes
**None planned** - All features are additive or opt-in

---

## References

### State-of-the-Art
- [Claude Code Context Window Management](https://dev.to/jsmanifest/claude-code-context-window-management-in-2026-what-gets-included-what-gets-dropped-and-how-to-26kh)
- [Aider Repository Map](https://aider.chat/docs/repomap.html)
- [GitHub Copilot Context Understanding](https://github.blog/ai-and-ml/github-copilot/how-github-copilot-is-getting-better-at-understanding-your-code/)

### Research Papers
- [Recursively Summarizing Enables Long-Term Dialogue Memory](https://arxiv.org/pdf/2308.15022)
- [AstraAI: AST-Guided Assistance for HPC Codebases](https://arxiv.org/pdf/2603.27423)
- [SaraCoder: Repository-Level Code Completion](https://arxiv.org/pdf/2508.10068)

### SOLID Principles
- Robert C. Martin, "Clean Architecture"
- Robert C. Martin, "Agile Software Development: Principles, Patterns, and Practices"

---

## Next Steps

1. **Review this document** with team for feedback
2. **Prioritize Phase 1** items for immediate implementation
3. **Set up project tracking** (GitHub issues/projects)
4. **Assign ownership** for each component
5. **Define success metrics** (token savings, latency, user satisfaction)
6. **Begin Phase 1 implementation** (Summarization + Metrics + Persistent files)

**Estimated Timeline:** 12 weeks for Phases 1-3, Phase 4 as time permits

**Estimated Effort:** 2-3 developers full-time or 1 developer + contributors

---

**Document Version:** 1.0
**Last Updated:** 2026-11-02
**Author:** Claude (Emiliano Context Engineering Team)
