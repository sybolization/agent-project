import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path


class SessionMemory:
    def __init__(self):
        self.current_task: Optional[str] = None
        self.important_files: List[str] = []
        self.workflows: List[str] = []
        self.errors_encountered: List[str] = []
        self.key_conclusions: List[str] = []
        self.todo_items: List[Dict[str, Any]] = []
        self.current_phase: Optional[str] = None
        self.last_updated: Optional[datetime] = None

    def update_from_messages(self, messages: list):
        if not messages:
            return
        
        for message in messages:
            if not isinstance(message, dict):
                continue
            
            role = message.get('role', '')
            content = message.get('content', '')
            
            if not content:
                continue
            
            if isinstance(content, str):
                self._extract_from_text(content, role)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        self._extract_from_text(item.get('text', ''), role)
        
        self.last_updated = datetime.now()

    def _extract_from_text(self, text: str, role: str):
        text_lower = text.lower()
        
        if role == 'user':
            if not self.current_task and len(text) > 10:
                task_indicators = ['search', 'find', 'analyze', 'research', 'investigate', 'look up', 'explore', '查看', '搜索', '分析']
                if any(indicator in text_lower for indicator in task_indicators):
                    self.current_task = text[:500]
        
        import re
        todo_pattern = r'\[\d+\]\s*(.+?):\s*(pending|in_progress|completed)'
        todo_matches = re.findall(todo_pattern, text, re.IGNORECASE)
        for match in todo_matches:
            todo_item = {"task": match[0].strip(), "status": match[1].lower()}
            if todo_item not in self.todo_items:
                self.todo_items.append(todo_item)
        
        file_patterns = ['.pdf', '.doc', '.txt', '.csv', '.json', '.py', '.js', '.html', '.xml']
        words = text.split()
        for word in words:
            if any(pattern in word.lower() for pattern in file_patterns):
                clean_file = word.strip('.,!?;:"\'()[]{}')
                if clean_file and clean_file not in self.important_files:
                    self.important_files.append(clean_file)
        
        if 'error' in text_lower or 'failed' in text_lower or 'exception' in text_lower or '错误' in text:
            if 'error' in text_lower:
                error_start = text_lower.find('error')
                error_context = text[max(0, error_start - 50):error_start + 150]
                if error_context not in self.errors_encountered:
                    self.errors_encountered.append(error_context.strip())
        
        conclusion_indicators = ['conclusion:', 'summary:', 'result:', 'finding:', 'therefore', 'thus', 'in summary', '结论', '总结']
        if any(indicator in text_lower for indicator in conclusion_indicators):
            sentences = text.split('.')
            for sentence in sentences:
                if any(indicator in sentence.lower() for indicator in conclusion_indicators):
                    clean_conclusion = sentence.strip()
                    if clean_conclusion and len(clean_conclusion) > 10:
                        if clean_conclusion not in self.key_conclusions:
                            self.key_conclusions.append(clean_conclusion)
        
        workflow_indicators = ['step 1', 'step 2', 'first,', 'then,', 'next,', 'finally,', 'after that', '第一步', '然后', '最后']
        if any(indicator in text_lower for indicator in workflow_indicators):
            if len(text) > 20:
                workflow_summary = text[:200] if len(text) > 200 else text
                if workflow_summary not in self.workflows:
                    self.workflows.append(workflow_summary)

    def to_summary(self) -> str:
        summary_parts = []
        
        if self.current_task:
            summary_parts.append(f"Current Task: {self.current_task}")
        
        if self.current_phase:
            summary_parts.append(f"Current Phase: {self.current_phase}")
        
        if self.todo_items:
            pending_todos = [t for t in self.todo_items if t.get("status") != "completed"]
            if pending_todos:
                todos_str = "\n  - ".join([f"[{t.get('status', 'pending')}] {t.get('task', 'unknown')}" for t in pending_todos[:10]])
                summary_parts.append(f"Pending TODOs:\n  - {todos_str}")
        
        if self.important_files:
            files_str = "\n  - ".join(self.important_files[:10])
            summary_parts.append(f"Important Files:\n  - {files_str}")
        
        if self.workflows:
            workflows_str = "\n  - ".join(self.workflows[:5])
            summary_parts.append(f"Workflows:\n  - {workflows_str}")
        
        if self.errors_encountered:
            errors_str = "\n  - ".join(self.errors_encountered[:5])
            summary_parts.append(f"Errors Encountered:\n  - {errors_str}")
        
        if self.key_conclusions:
            conclusions_str = "\n  - ".join(self.key_conclusions[:5])
            summary_parts.append(f"Key Conclusions:\n  - {conclusions_str}")
        
        if self.last_updated:
            summary_parts.append(f"Last Updated: {self.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n\n".join(summary_parts) if summary_parts else "No session memory data available."

    def save_to_file(self, path: str):
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'current_task': self.current_task,
            'important_files': self.important_files,
            'workflows': self.workflows,
            'errors_encountered': self.errors_encountered,
            'key_conclusions': self.key_conclusions,
            'todo_items': self.todo_items,
            'current_phase': self.current_phase,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_file(self, path: str):
        file_path = Path(path)
        
        if not file_path.exists():
            return
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.current_task = data.get('current_task')
        self.important_files = data.get('important_files', [])
        self.workflows = data.get('workflows', [])
        self.errors_encountered = data.get('errors_encountered', [])
        self.key_conclusions = data.get('key_conclusions', [])
        self.todo_items = data.get('todo_items', [])
        self.current_phase = data.get('current_phase')
        
        last_updated_str = data.get('last_updated')
        if last_updated_str:
            self.last_updated = datetime.fromisoformat(last_updated_str)
