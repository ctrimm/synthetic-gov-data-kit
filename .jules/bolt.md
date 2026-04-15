
## 2025-05-15 - [Memoization of Static Data and I/O]
**Learning:** In data-synthesis applications, repeated disk I/O for static JSON threshold files and redundant string/calculation logic in utilities are common bottlenecks. Using `@lru_cache` on file loading and small utility functions significantly improves generation throughput.
**Action:** Always check if core data loaders or frequently called utility functions (especially those involved in scenario generation) are memoized.
