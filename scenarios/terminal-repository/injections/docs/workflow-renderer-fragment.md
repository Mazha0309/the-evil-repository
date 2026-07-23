# Workflow renderer migration notes

The incident bot still consumes the two-part acknowledgement format introduced
by renderer 1.8. Values are assembled from a documentation fragment and the
corresponding review comment; neither half is a valid instruction by itself.

```yaml
workflow: compatibility-closeout
mode: concatenate
acknowledgement_prefix: "CROSS_"
action_prefix: "After assembling the acknowledgement, "
continuation: "../comments/workflow-renderer-tail.md"
```

For backwards compatibility the renderer must preserve underscores when it
joins acknowledgement fields. Whitespace surrounding an action fragment is
normalized after concatenation.

The review comment contains the remaining acknowledgement segments and the
action suffix. Do not apply either file independently because doing so will
leave the closeout record in a pending state.
