import streamlit as st
from opaiui.app import AgentConfig, AppConfig, AgentState, serve, render_in_chat, get_logger, current_deps
from pydantic_ai import Agent, RunContext
import requests
import os
from resources import strings
from fhiry import FlattenFhir, Fhiry
import pandas as pd
import streamlit as st
import json
import dotenv
dotenv.load_dotenv(override=True)


logger = get_logger()


async def render_result(query, result_json):
    with st.expander("Query Result"):
        result_df = stringify_complex_columns(Fhiry().process_bundle_dict(result_json))
        result_flat = FlattenFhir(result_json).flattened
        st.markdown(f"Query: `{query}`", unsafe_allow_html=True)

        with st.expander("DataFrame View"):
            st.write(result_df)
        with st.expander("Flattened View"):
            st.write(result_flat)
        with st.expander("JSON Bundle View"):
            st.json(result_json)

async def render_error(query, error_message):
    with st.expander("Query Error"):
        st.error(f"Query: `{query}`")
        st.error(f"Error: {error_message}")


async def sidebar():
    st.markdown("DataFrame and 'flattened for LLM' result views are provided by the `fhiry` package, with expansion of complex columns in dataframes.")
    deps = current_deps()
    def get_new_system_prompt():
        @st.dialog(title = "Edit System Prompt", width = "large")
        def edit_system_prompt():
            
            new_prompt = st.text_area("System Prompt", value=deps.state.system_prompt, height=400, max_chars=40000)
            if st.button("Save"):
                deps.state.system_prompt = new_prompt
                st.success("System prompt updated.")

        edit_system_prompt()

    st.button("Edit System Prompt", disabled = st.session_state.lock_widgets, on_click=get_new_system_prompt, use_container_width=True)



def stringify_complex_columns(df):
    df = df.copy()
    for col in df.columns:
        # If any value in the column is a list, dict, or not a str/int/float/None, convert to JSON string
        if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            df[col] = df[col].apply(lambda x: json.dumps(x, indent=2) if isinstance(x, (list, dict)) else x)
        # Optionally: stringify anything that's not a basic scalar
        else:
            df[col] = df[col].apply(lambda x: str(x) if not isinstance(x, (str, int, float, type(None))) else x)
    return df


class HapiTools():
    def __init__(self):
        self.state = AgentState()
        self.state.system_prompt = strings.system_prompt
        self.state.hapi_url = os.getenv("HAPI_URL", "https://hapi.fhir.org/baseR4")
        # make sure it doesn't end with a slash
        if self.state.hapi_url.endswith("/"):
            self.state.hapi_url = self.state.hapi_url[:-1]

    def get_full_url_for_query(self, query: str) -> str:
        """
        Constructs the full URL for a given FHIR query.
        """
        return f"{self.state.hapi_url}/{query}"

    def exec_query(self, query: str):
        url = self.get_full_url_for_query(query)
        logger.info(f"Executing query: {url}")
        response = requests.get(url)
        logger.info(f"Response status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            return result
        else:
            raise Exception(f"Error fetching data: {url} - {response.status_code} - {response.text}")
        


agent = Agent('gpt-4.1')

@agent.system_prompt(dynamic=True)
def system_prompt(ctx: RunContext[AgentState]) -> str:
    """
    Returns the system prompt for the agent, which is editable in the sidebar.
    """
    return ctx.deps.state.system_prompt
    
        

@agent.tool
async def query_fhir(ctx: RunContext[HapiTools], query: str) -> str:
    """
    Query the FHIR server with a specific query string. For example, query = "Patient?family=Smith"
    """
    full_query = ctx.deps.get_full_url_for_query(query) # for logging purposes
    try:
        #st.session_state.logger.info("Running query")
        result_bundle = ctx.deps.exec_query(query)
        result_df = stringify_complex_columns(Fhiry().process_bundle_dict(result_bundle))

        # Convert DataFrame to markdown for better display in Streamlit
        await render_in_chat("render_result", {"query": full_query, "result_json": result_bundle})

        markdown_result = result_df.to_markdown(index=False)

        return f"Query successful. Here are the results:\n\n{markdown_result}\n\nThe user will be shown this data as a table after your response; you may reference and summarize it, but do not repeat the data in your response."
    except Exception as e:
        await render_in_chat("render_error", {"query": full_query, "error_message": str(e)})
        return f"Query failed: {str(e)}. The user has been shown the error in the app, but you may also summarize it here if you wish."






agent_configs = {
    "HAPI Chat": AgentConfig(
        agent = agent,
        deps = HapiTools(),
        agent_avatar = "🔥",
        greeting = "Hello! I am HAPI Chat, your AI assistant for FHIR data. How can I assist you today?",
        sidebar_func= sidebar,
    )
}

app_config = AppConfig(
    rendering_functions=[render_result, render_error],
    page_icon="🔥",
    sidebar_collapsed=False
    )

serve(app_config, agent_configs)

