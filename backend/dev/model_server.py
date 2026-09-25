"""Minimal OpenAI-compatible stand-in for the Nano's model servers.

The production servers are expected to speak the same API (vLLM does), so
backend code written against this works unchanged there.

  python backend/dev/model_server.py chat  --port 8000 [--model Qwen/Qwen3-4B-Instruct-2507]
  python backend/dev/model_server.py embed --port 8003 [--model BAAI/bge-small-en-v1.5]

Run with the `zgx` conda env (torch, transformers, fastapi, uvicorn).
"""
import argparse
import threading
import time

import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

DEFAULTS = {'chat': 'Qwen/Qwen3-4B-Instruct-2507', 'embed': 'BAAI/bge-small-en-v1.5'}


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str | None = None


def build(role, name):
    app = FastAPI()
    tok = AutoTokenizer.from_pretrained(name)
    lock = threading.Lock()  # one generation at a time; fine for a single-user demo

    @app.get('/v1/models')
    def models():
        return {'object': 'list', 'data': [{'id': name, 'object': 'model'}]}

    if role == 'chat':
        model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.bfloat16, device_map='cuda').eval()

        @app.post('/v1/chat/completions')
        def chat(req: ChatRequest):
            ids = tok.apply_chat_template([m.model_dump() for m in req.messages], add_generation_prompt=True,
                                          return_tensors='pt', return_dict=True).to(model.device)
            sample = req.temperature > 0
            with lock, torch.inference_mode():
                t0 = time.perf_counter()
                out = model.generate(**ids, max_new_tokens=req.max_tokens, do_sample=sample,
                                     temperature=req.temperature if sample else None, top_p=None, top_k=None)
                ms = round((time.perf_counter() - t0) * 1000)
            new = out[0, ids['input_ids'].shape[1]:]
            text = tok.decode(new, skip_special_tokens=True).strip()
            return {'object': 'chat.completion', 'model': name,
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': ids['input_ids'].shape[1], 'completion_tokens': len(new)},
                    'x_generate_ms': ms}
    else:
        model = AutoModel.from_pretrained(name).to('cuda').eval()

        @app.post('/v1/embeddings')
        def embed(req: EmbedRequest):
            texts = [req.input] if isinstance(req.input, str) else req.input
            batch = tok(texts, padding=True, truncation=True, max_length=512, return_tensors='pt').to(model.device)
            with lock, torch.inference_mode():
                cls = model(**batch).last_hidden_state[:, 0]  # bge uses CLS pooling
            vecs = torch.nn.functional.normalize(cls, dim=-1).float().cpu().tolist()
            return {'object': 'list', 'model': name,
                    'data': [{'object': 'embedding', 'index': i, 'embedding': v} for i, v in enumerate(vecs)]}
    return app


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('role', choices=['chat', 'embed'])
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--model')
    a = p.parse_args()
    uvicorn.run(build(a.role, a.model or DEFAULTS[a.role]), host='127.0.0.1', port=a.port)
