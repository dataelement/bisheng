"""Chain for interacting with SQL Database."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain.callbacks.manager import AsyncCallbackManagerForChainRun, CallbackManagerForChainRun
from langchain.chains.llm import LLMChain
from langchain.prompts.prompt import PromptTemplate
from langchain.tools.sql_database.prompt import QUERY_CHECKER
from langchain_experimental.sql import SQLDatabaseChain as SQLDatabaseChainExperimental

INTERMEDIATE_STEPS_KEY = 'intermediate_steps'


class SQLDatabaseChain(SQLDatabaseChainExperimental):
    """Chain for interacting with SQL Database.

    Example:
        .. code-block:: python

            from langchain_experimental.sql import SQLDatabaseChain
            from langchain.llms import OpenAI, SQLDatabase
            db = SQLDatabase(...)
            db_chain = SQLDatabaseChain.from_llm(OpenAI(), db)

    *Security note*: Make sure that the database connection uses credentials
        that are narrowly-scoped to only include the permissions this chain needs.
        Failure to do so may result in data corruption or loss, since this chain may
        attempt commands like `DROP TABLE` or `INSERT` if appropriately prompted.
        The best way to guard against such negative outcomes is to (as appropriate)
        limit the permissions granted to the credentials used with this chain.
        This issue shows an example negative outcome if these steps are not taken:
        https://github.com/langchain-ai/langchain/issues/5923
    """

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        input_text = f'{inputs[self.input_key]}\nSQLQuery:'
        await _run_manager.on_text(input_text, verbose=self.verbose)
        # If not present, then defaults to None which is all tables.
        table_names_to_use = inputs.get('table_names_to_use')
        table_info = self.database.get_table_info(table_names=table_names_to_use)
        llm_inputs = {
            'input': input_text,
            'top_k': str(self.top_k),
            'dialect': self.database.dialect,
            'table_info': table_info,
            'stop': ['\nSQLResult:'],
        }
        if self.memory is not None:
            for k in self.memory.memory_variables:
                llm_inputs[k] = inputs[k]
        intermediate_steps: List = []
        try:
            intermediate_steps.append(llm_inputs.copy())  # input: sql generation
            sql_cmd = await self.llm_chain.apredict(
                callbacks=_run_manager.get_child(),
                **llm_inputs,
            )
            sql_cmd = sql_cmd.strip()
            if self.return_sql:
                return {self.output_key: sql_cmd}
            if not self.use_query_checker:
                await _run_manager.on_text(sql_cmd, color='green', verbose=self.verbose)
                intermediate_steps.append(sql_cmd)  # output: sql generation (no checker)
                intermediate_steps.append({'sql_cmd': sql_cmd})  # input: sql exec
                result = self.database.run(sql_cmd)
                intermediate_steps.append(str(result))  # output: sql exec
            else:
                query_checker_prompt = self.query_checker_prompt or PromptTemplate(
                    template=QUERY_CHECKER, input_variables=['query', 'dialect'])
                query_checker_chain = LLMChain(llm=self.llm_chain.llm, prompt=query_checker_prompt)
                query_checker_inputs = {
                    'query': sql_cmd,
                    'dialect': self.database.dialect,
                }
                checked_sql_command: str = await query_checker_chain.apredict(
                    callbacks=_run_manager.get_child(), **query_checker_inputs)
                checked_sql_command = checked_sql_command.strip()
                intermediate_steps.append(checked_sql_command)  # output: sql generation (checker)
                await _run_manager.on_text(checked_sql_command,
                                           color='green',
                                           verbose=self.verbose)
                intermediate_steps.append({'sql_cmd': checked_sql_command})  # input: sql exec
                result = self.database.run(checked_sql_command)
                intermediate_steps.append(str(result))  # output: sql exec
                sql_cmd = checked_sql_command

            await _run_manager.on_text('\nSQLResult: ', verbose=self.verbose)
            await _run_manager.on_text(result, color='yellow', verbose=self.verbose)
            # If return direct, we just set the final result equal to
            # the result of the sql query result, otherwise try to get a human readable
            # final answer
            if self.return_direct:
                final_result = result
            else:
                await _run_manager.on_text('\nAnswer:', verbose=self.verbose)
                input_text += f'{sql_cmd}\nSQLResult: {result}\nAnswer:'
                llm_inputs['input'] = input_text
                intermediate_steps.append(llm_inputs.copy())  # input: final answer
                final_result = await self.llm_chain.apredict(
                    callbacks=_run_manager.get_child(),
                    **llm_inputs,
                )
                final_result = final_result.strip()
                intermediate_steps.append(final_result)  # output: final answer
                await _run_manager.on_text(final_result, color='green', verbose=self.verbose)
            chain_result: Dict[str, Any] = {self.output_key: final_result}
            if self.return_intermediate_steps:
                chain_result[INTERMEDIATE_STEPS_KEY] = intermediate_steps
            return chain_result
        except Exception as exc:
            # Append intermediate steps to exception, to aid in logging and later
            # improvement of few shot prompt seeds
            exc.intermediate_steps = intermediate_steps  # type: ignore
            raise exc
