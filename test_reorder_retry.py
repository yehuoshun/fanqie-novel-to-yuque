#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_reorder_retry.py — reorder_toc.py 重试逻辑回归单测
========================================================
不联网：monkeypatch 网络层（subprocess.run / get_toc_docs / mcporter_call），
验证「stdio 抽风重试」「MCP error 不重试」「移动失败重试 3 轮」行为。

用法:
    python3 test_reorder_retry.py
"""
import json
import os
import reorder_toc

# ---------- 测试 1：输出解析失败 → 重试 retries 次后放弃 ----------
calls = {'n': 0}


def fake_run_bad(cmd, **kw):
    calls['n'] += 1

    class R:
        stdout = 'not json at all'
        stderr = ''
        returncode = 1
    return R()


orig_run = reorder_toc.subprocess.run
reorder_toc.subprocess.run = fake_run_bad
r = reorder_toc.mcporter_call('yuque_get_toc', {'book_id': '1'}, retries=2)
assert r is None and calls['n'] == 3, f"应重试3次后放弃，实际 {calls['n']} 次"
print("✅ 坏输出：重试 3 次后放弃")

# ---------- 测试 2：MCP error（参数/权限错误）不重试 ----------
calls['n'] = 0


def fake_run_mcperr(cmd, **kw):
    calls['n'] += 1

    class R:
        stdout = 'MCP error: book_id must be string'
        stderr = ''
        returncode = 1
    return R()


reorder_toc.subprocess.run = fake_run_mcperr
r = reorder_toc.mcporter_call('yuque_get_toc', {'book_id': '1'}, retries=2)
assert r is None and calls['n'] == 1, f"MCP error 不应重试，实际 {calls['n']} 次"
print("✅ MCP error：不重试，直接失败")

# ---------- 测试 3：坏输出后第 2 次成功 ----------
calls['n'] = 0


def fake_run_then_ok(cmd, **kw):
    calls['n'] += 1

    class R:
        stdout = 'not json' if calls['n'] == 1 else json.dumps({'ok': True})
        stderr = ''
        returncode = 1 if calls['n'] == 1 else 0
    return R()


reorder_toc.subprocess.run = fake_run_then_ok
r = reorder_toc.mcporter_call('yuque_get_toc', {'book_id': '1'}, retries=2)
assert r == {'ok': True} and calls['n'] == 2, f"应第2次成功，实际 {calls['n']} 次"
print("✅ 坏输出后第 2 次成功：正常返回")

reorder_toc.subprocess.run = orig_run

# ---------- 测试 4：单节点移动失败重试 3 轮后成功 ----------
seq = {'get': 0, 'move': 0}


def fake_get_toc(book_id):
    seq['get'] += 1
    if seq['get'] == 1:  # 初始：乱序 B,A
        return [{'type': 'DOC', 'title': 'B', 'uuid': 'b'},
                {'type': 'DOC', 'title': 'A', 'uuid': 'a'}]
    return [{'type': 'DOC', 'title': 'A', 'uuid': 'a'},  # 复验：正确顺序
            {'type': 'DOC', 'title': 'B', 'uuid': 'b'}]


def fake_call(tool, args_dict, timeout=60, retries=2):
    if tool == 'yuque_update_toc':
        seq['move'] += 1
        if seq['move'] <= 2:  # 前两轮失败
            return None
        return {'data': 'ok'}
    return None


reorder_toc.get_toc_docs = fake_get_toc
reorder_toc.mcporter_call = fake_call

tmp = '/tmp/reorder_test_chapters.json'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump([['A', ''], ['B', '']], f, ensure_ascii=False)
ok = reorder_toc.reorder('1', tmp, verbose=False)
assert ok, "reorder 应成功"
assert seq['move'] == 3, f"移动应重试到第 3 轮，实际 {seq['move']} 轮"
os.remove(tmp)
print("✅ 单节点移动：前 2 轮失败后第 3 轮成功")

# ---------- 测试 5：3 轮全失败 → 中止返回 False ----------
seq = {'get': 0, 'move': 0}


def fake_get_toc2(book_id):
    seq['get'] += 1
    if seq['get'] == 1:
        return [{'type': 'DOC', 'title': 'B', 'uuid': 'b'},
                {'type': 'DOC', 'title': 'A', 'uuid': 'a'}]
    return [{'type': 'DOC', 'title': 'A', 'uuid': 'a'},
            {'type': 'DOC', 'title': 'B', 'uuid': 'b'}]


def fake_call2(tool, args_dict, timeout=60, retries=2):
    if tool == 'yuque_update_toc':
        seq['move'] += 1
        return None  # 永远失败
    return None


reorder_toc.get_toc_docs = fake_get_toc2
reorder_toc.mcporter_call = fake_call2

with open(tmp, 'w', encoding='utf-8') as f:
    json.dump([['A', ''], ['B', '']], f, ensure_ascii=False)
ok = reorder_toc.reorder('1', tmp, verbose=False)
assert not ok, "3 轮全失败应中止返回 False"
assert seq['move'] == 3, f"应恰好 3 轮，实际 {seq['move']}"
os.remove(tmp)
print("✅ 3 轮全失败：中止返回 False，不无限重试")

print("\n🎉 全部 5 项测试通过")
