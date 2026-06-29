# LangGraph Diagram (New Architecture)

`mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	input_router(input_router)
	intent_classifier(intent_classifier)
	conflict_batch_resolver(conflict_batch_resolver)
	confirm_subgraph_handler(confirm_subgraph_handler)
	mutation_executor(mutation_executor)
	query_handler(query_handler)
	post_process(post_process)
	__end__([<p>__end__</p>]):::last
	__start__ --> input_router;
	confirm_subgraph_handler -. &nbsp;success&nbsp; .-> mutation_executor;
	confirm_subgraph_handler -. &nbsp;cancel&nbsp; .-> post_process;
	conflict_batch_resolver -. &nbsp;execute&nbsp; .-> mutation_executor;
	conflict_batch_resolver -. &nbsp;pending&nbsp; .-> post_process;
	input_router -. &nbsp;go_to_confirm_handler&nbsp; .-> confirm_subgraph_handler;
	input_router -. &nbsp;go_to_intent_classifier&nbsp; .-> intent_classifier;
	input_router -. &nbsp;end_early&nbsp; .-> post_process;
	intent_classifier -. &nbsp;mutation&nbsp; .-> conflict_batch_resolver;
	intent_classifier -. &nbsp;query&nbsp; .-> query_handler;
	mutation_executor --> post_process;
	query_handler --> post_process;
	post_process --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

`
