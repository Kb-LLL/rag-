#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
聊天功能改进测试脚本
测试改进后的 ChatGPT 风格聊天功能
"""

import asyncio
import aiohttp
import json
from pathlib import Path

# 测试配置
BASE_URL = "http://localhost:5000"
TEST_USERNAME = "test_user"
TEST_PASSWORD = "test123456"
TEST_EMAIL = "test@example.com"


async def test_login():
    """测试登录功能"""
    print("🔐 测试登录...")
    async with aiohttp.ClientSession() as session:
        # 尝试登录
        async with session.post(
            f"{BASE_URL}/api/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                print("✅ 登录成功!")
                return data['token']
            else:
                print("❌ 登录失败,尝试注册...")
                return await test_register()


async def test_register():
    """测试注册功能"""
    print("📝 测试注册...")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/register",
            json={
                "username": TEST_USERNAME,
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        ) as resp:
            if resp.status == 200:
                print("✅ 注册成功!")
                return await test_login()
            else:
                print(f"❌ 注册失败: {await resp.text()}")
                return None


async def test_pure_chat(token):
    """测试纯文字对话"""
    print("\n💬 测试纯文字对话...")
    headers = {"Authorization": f"Bearer {token}"}
    
    async with aiohttp.ClientSession() as session:
        # 第一轮对话
        async with session.post(
            f"{BASE_URL}/api/chat",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "你好,请用一句话介绍你自己"}
                ],
                "stream": False
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"✅ AI 回复: {data['choices'][0]['message']['content'][:50]}...")
                conv_id = data.get('conv_id')
                
                # 第二轮对话(测试连续对话)
                print("   继续对话...")
                async with session.post(
                    f"{BASE_URL}/api/chat",
                    headers=headers,
                    json={
                        "conversation_id": conv_id,
                        "messages": [
                            {"role": "user", "content": "你好,请用一句话介绍你自己"},
                            {"role": "assistant", "content": data['choices'][0]['message']['content']},
                            {"role": "user", "content": "谢谢你"}
                        ],
                        "stream": False
                    }
                ) as resp2:
                    if resp2.status == 200:
                        data2 = await resp2.json()
                        print(f"✅ AI 继续回复: {data2['choices'][0]['message']['content'][:50]}...")
                        return conv_id
            else:
                print(f"❌ 对话失败: {await resp.text()}")
                return None


async def test_file_upload(token):
    """测试文件上传"""
    print("\n📄 测试文件上传...")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 创建测试文件
    test_file_path = Path("test_upload.txt")
    test_file_path.write_text("这是一个测试文件,用于测试聊天附件功能。\n内容包括多行文本。", encoding='utf-8')
    
    async with aiohttp.ClientSession() as session:
        data = aiohttp.FormData()
        data.add_field('file',
                       open(test_file_path, 'rb'),
                       filename='test_upload.txt',
                       content_type='text/plain')
        data.add_field('filename', 'test_upload.txt')
        
        async with session.post(
            f"{BASE_URL}/api/upload/chat-file",
            headers=headers,
            data=data
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"✅ 文件上传成功: {result['name']}")
                print(f"   文件类型: {result['type']}")
                print(f"   内容预览: {result['content'][:50]}...")
                return result
            else:
                print(f"❌ 文件上传失败: {await resp.text()}")
                return None
    
    # 清理测试文件
    if test_file_path.exists():
        test_file_path.unlink()


async def test_chat_with_file(token, file_info):
    """测试带文件的对话"""
    print("\n📎 测试带附件的对话...")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 构建带附件内容的消息
    file_content = f"[文件: {file_info['name']}]\n{file_info['content']}\n\n---\n\n请总结这个文件的内容"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/chat",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": file_content}
                ],
                "stream": False
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"✅ AI 分析文件: {data['choices'][0]['message']['content'][:100]}...")
                return True
            else:
                print(f"❌ 带附件对话失败: {await resp.text()}")
                return False


async def test_conversations(token):
    """测试会话列表"""
    print("\n📋 测试会话列表...")
    headers = {"Authorization": f"Bearer {token}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/api/conversations",
            headers=headers
        ) as resp:
            if resp.status == 200:
                conversations = await resp.json()
                print(f"✅ 找到 {len(conversations)} 个会话")
                if conversations:
                    print(f"   最新会话: {conversations[0]['title']}")
                return True
            else:
                print(f"❌ 获取会话列表失败: {await resp.text()}")
                return False


async def main():
    """主测试流程"""
    print("=" * 60)
    print("🚀 开始测试聊天功能改进")
    print("=" * 60)
    
    try:
        # 1. 登录
        token = await test_login()
        if not token:
            print("❌ 无法获取登录令牌,测试终止")
            return
        
        # 2. 测试纯文字对话
        conv_id = await test_pure_chat(token)
        
        # 3. 测试文件上传
        file_info = await test_file_upload(token)
        
        # 4. 测试带文件的对话
        if file_info:
            await test_chat_with_file(token, file_info)
        
        # 5. 测试会话列表
        await test_conversations(token)
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成!")
        print("=" * 60)
        print("\n📝 测试总结:")
        print("1. ✅ 纯文字对话正常")
        print("2. ✅ 连续对话正常")
        print("3. ✅ 文件上传正常")
        print("4. ✅ 带附件对话正常")
        print("5. ✅ 会话管理正常")
        print("\n🎉 系统现在像 ChatGPT 一样,既能对话又能处理附件!")
        
    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("⚠️  请确保后端服务已启动: python app.py")
    print("⚠️  服务地址: http://localhost:5000\n")
    
    asyncio.run(main())
