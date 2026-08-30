# -*- coding: utf-8 -*-
"""
Export complete chat history and dialogue turns to JSON format.
"""

import json
import re
import os

def main():
    transcript_path = r'C:\Users\KKU650001\.gemini\antigravity\brain\bb38fc00-73fc-4fc3-8fff-0d9a58e4d0cd\.system_generated\logs\transcript_full.jsonl'

    if not os.path.exists(transcript_path):
        print(f"Transcript file not found at: {transcript_path}")
        return

    raw_events = []
    with open(transcript_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    raw_events.append(json.loads(line))
                except Exception as err:
                    print(f"Error reading line: {err}")

    # Parse conversational history into clean structured turns
    turns = []
    current_turn = None

    def extract_user_request(text):
        if not text:
            return ''
        m = re.search(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        clean = re.sub(r'<[^>]+>', '', text).strip()
        return clean

    for event in raw_events:
        t = event.get('type')
        src = event.get('source')
        content = event.get('content') or ''
        created_at = event.get('created_at')
        tool_calls = event.get('tool_calls') or []
        
        if t == 'USER_INPUT' and src == 'USER_EXPLICIT':
            req_text = extract_user_request(content)
            images = re.findall(r'([A-Za-z0-9_/\\]+\.(?:png|jpg|jpeg|webp))', content)
            
            current_turn = {
                'turn_number': len(turns) + 1,
                'timestamp': created_at,
                'role': 'user',
                'request': req_text,
                'attached_images': images,
                'assistant_response': '',
                'tool_actions': []
            }
            turns.append(current_turn)
        elif t == 'PLANNER_RESPONSE' and current_turn:
            if content:
                if current_turn['assistant_response']:
                    current_turn['assistant_response'] += '\n\n' + content
                else:
                    current_turn['assistant_response'] = content
            
            for tc in tool_calls:
                fn = tc.get('function', {})
                name = fn.get('name')
                args = fn.get('arguments')
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        pass
                summary = args.get('toolSummary') if isinstance(args, dict) else ''
                action = args.get('toolAction') if isinstance(args, dict) else ''
                current_turn['tool_actions'].append({
                    'tool': name,
                    'summary': summary,
                    'action': action
                })

    chat_export = {
        'conversation_id': 'bb38fc00-73fc-4fc3-8fff-0d9a58e4d0cd',
        'project_name': 'KKUL Map Navigation System',
        'exported_at': '2026-08-30T14:31:00+07:00',
        'total_dialogue_turns': len(turns),
        'messages': turns
    }

    # 1. Clean structured chat export
    out_path = 'chat_history.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(chat_export, f, indent=2, ensure_ascii=False)

    # 2. Complete raw transcript events export
    raw_out_path = 'chat_history_full_raw.json'
    with open(raw_out_path, 'w', encoding='utf-8') as f:
        json.dump(raw_events, f, indent=2, ensure_ascii=False)

    size_clean = os.path.getsize(out_path)
    size_raw = os.path.getsize(raw_out_path)

    print(f"✅ Exported clean chat history: {out_path} ({len(turns)} turns, {size_clean:,} bytes)")
    print(f"✅ Exported full raw logs: {raw_out_path} ({len(raw_events)} events, {size_raw:,} bytes)")

if __name__ == '__main__':
    main()
