# Mathematical verification skill

This verifier-only guidance adapts the `verify` workflow from the installed `math-reasoning`
skill. The grading prompt, rubric, and requested JSON schema remain authoritative.

- Independently reconstruct the key mathematical argument before assessing it.
- State assumptions explicitly in criterion reasoning when they affect correctness.
- Check that every symbol used in a decisive step is defined or unambiguous in context.
- Check notation consistency, dimensions or units, signs, normalization factors, limiting cases,
  and relevant boundary or critical cases.
- Verify algebraic transformations and low-order expansions step by step when they determine a
  rubric result.
- Accept an alternative method when it establishes the required claim under valid assumptions.
- Do not infer missing work. Record unresolved ambiguity in that criterion's `concerns`.
- Do not produce a proof document, LaTeX wrapper, score summary, or fields outside the requested
  JSON schema.
