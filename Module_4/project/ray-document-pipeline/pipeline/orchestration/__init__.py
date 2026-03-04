"""
orchestration — Ray Cluster Coordination for the Document Processing Pipeline

This package manages the control plane:
  - orchestrator.py : Polling loop, Ray init, SIGTERM handling, concurrent batch dispatch
  - tasks.py        : @ray.remote wrappers that call stages/ modules on Ray workers
  - dynamodb.py     : DynamoDB control/audit table operations (query, claim, update)

Separation rationale:
  stages/ contains pure business logic (extract, chunk, enrich, embed, load).
  orchestration/ contains Ray infrastructure — scheduling, state management,
  and lifecycle. This lets you unit-test stages without Ray or DynamoDB.

Author: Prudhvi | Thoughtworks
"""
