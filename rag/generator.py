import json
from typing import List, Dict, Any, Optional, AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from config import load_config

_llm = None
_llm_settings = None

def get_llm():
    global _llm, _llm_settings
    config = load_config()
    settings = (
        config['model-name'],
        config['api-key'],
        config['base-url'],
    )
    if _llm is None or _llm_settings != settings:
        _llm = ChatOpenAI(
            model=settings[0],
            openai_api_key=settings[1],
            openai_api_base=settings[2],
            streaming=True,
            temperature=0,
            max_tokens=2048,
        )
        _llm_settings = settings
    return _llm

RAG_SYSTEM_PROMPT = """你是一个基于知识库的智能问答助手。请根据提供的参考信息回答用户的问题。

要求：
1. 严格基于提供的参考信息回答问题，不要编造不存在的知识
2. 如果参考信息不足以回答问题，请明确说明
3. 引用来源时标注编号，如 [1][2]
4. 回答要简洁准确，条理清晰
5. 如果用户用中文提问，用中文回答；用英文提问，用英文回答
6. 每个事实性结论必须紧跟来源编号，如 [1] 或 [1][2]
7. 参考信息没有覆盖的问题，明确回答“知识库中没有足够信息”，不要使用模型常识补写"""

def build_rag_messages(query: str, context: str, history: Optional[List[Dict]] = None) -> List:
    messages = [SystemMessage(content=RAG_SYSTEM_PROMPT)]

    if history:
        for msg in history[-6:]:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'user':
                messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                from langchain.schema import AIMessage
                messages.append(AIMessage(content=content))

    user_content = f"参考信息：\n{context}\n\n用户问题：{query}"
    messages.append(HumanMessage(content=user_content))
    return messages

async def rag_generate_stream(
    query: str,
    context: str,
    history: Optional[List[Dict]] = None,
) -> AsyncGenerator[str, None]:
    llm = get_llm()
    messages = build_rag_messages(query, context, history)

    full_response = ""
    try:
        async for chunk in llm.astream(messages):
            content = chunk.content
            if content:
                full_response += content
                yield json.dumps({'content': content})
    except Exception as e:
        yield json.dumps({'error': str(e)})

    yield json.dumps({'done': True})

async def rag_generate(
    query: str,
    context: str,
    history: Optional[List[Dict]] = None,
) -> str:
    llm = get_llm()
    messages = build_rag_messages(query, context, history)
    response = await llm.ainvoke(messages)
    return response.content
