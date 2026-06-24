import requests
BASE = 'http://localhost:5000'

r = requests.post(f'{BASE}/api/login', json={'username':'vueuser','password':'123456'})
if r.status_code != 200:
    r = requests.post(f'{BASE}/api/register', json={'username':'vueuser','email':'rag@test.com','password':'123456'})
    r = requests.post(f'{BASE}/api/login', json={'username':'vueuser','password':'123456'})

token = r.json()['token']
h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
print(f'[Login] OK token={token[:20]}...')

# 1. Add knowledge
docs = [
    {'title': 'Python基础', 'content': 'Python是一种高级编程语言，由Guido van Rossum于1991年创建。Python以简洁易读的语法著称，广泛应用于Web开发、数据分析、人工智能等领域。Python的设计哲学强调代码的可读性和简洁性。'},
    {'title': '机器学习简介', 'content': '机器学习是人工智能的一个分支，使计算机能够从数据中学习和改进。主要分为监督学习、无监督学习和强化学习。常见的算法包括线性回归、决策树、支持向量机和神经网络。'},
    {'title': 'FastAPI框架', 'content': 'FastAPI是一个现代、快速的Python Web框架，用于构建API。它基于Starlette和Pydantic，具有自动生成OpenAPI文档、类型检查和异步支持等特性。FastAPI的性能与Node.js和Go相当。'},
]
for doc in docs:
    r = requests.post(f'{BASE}/api/knowledge-base', json=doc, headers=h)
    print(f'[Add KB] {r.status_code} id={r.json().get("id","?")[:8]}...')
    d = r.json()

# 2. List knowledge base
r = requests.get(f'{BASE}/api/knowledge-base', headers=h)
print(f'[List KB] {r.status_code} count={len(r.json())}')

# 3. RAG query
print('\n=== RAG Query ===')
r = requests.post(f'{BASE}/api/rag/query', json={
    'query': 'Python适合做什么？',
    'top_k': 3,
    'stream': False
}, headers=h)
print(f'[RAG] {r.status_code}')
data = r.json()
print(f'  Answer: {data["answer"][:150]}...')
print(f'  Sources: {data["sources"]}')
print(f'  Use RAG: {data["use_rag"]}')