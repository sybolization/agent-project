"""Unit tests for ContextCompressor class."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.context.compression import (
    ContextCompressor,
    CompressionStats,
    estimate_context_tokens,
    compact_by_rounds,
    compress_context,
    emergency_compact,
)
from agent.state import AgentState, AgentPhase
from agent.session.memory import SessionMemory


class TestCompressionStats:
    """Tests for CompressionStats dataclass."""
    
    def test_default_values(self):
        """Test default values of CompressionStats."""
        stats = CompressionStats()
        
        assert stats.original_tokens == 0
        assert stats.final_tokens == 0
        assert stats.compression_count == 0
        assert stats.levels_used == []
        assert stats.transcript_path is None
    
    def test_tokens_saved(self):
        """Test tokens_saved property."""
        stats = CompressionStats(original_tokens=1000, final_tokens=600)
        
        assert stats.tokens_saved == 400
    
    def test_tokens_saved_no_savings(self):
        """Test tokens_saved when no compression occurred."""
        stats = CompressionStats(original_tokens=500, final_tokens=600)
        
        assert stats.tokens_saved == 0
    
    def test_compression_ratio(self):
        """Test compression_ratio property."""
        stats = CompressionStats(original_tokens=1000, final_tokens=600)
        
        assert stats.compression_ratio == 0.6
    
    def test_compression_ratio_zero_original(self):
        """Test compression_ratio when original_tokens is zero."""
        stats = CompressionStats(original_tokens=0, final_tokens=0)
        
        assert stats.compression_ratio == 0.0


class TestContextCompressor:
    """Tests for ContextCompressor class."""
    
    @pytest.fixture
    def compressor(self):
        """Create a ContextCompressor instance with default settings."""
        return ContextCompressor()
    
    @pytest.fixture
    def compressor_enabled(self):
        """Create a ContextCompressor instance with compression enabled."""
        return ContextCompressor(
            compression_enabled=True,
            compress_threshold=1000,
            context_window_max=2000,
            keep_rounds=5,
        )
    
    @pytest.fixture
    def compressor_disabled(self):
        """Create a ContextCompressor instance with compression disabled."""
        return ContextCompressor(compression_enabled=False)
    
    @pytest.fixture
    def agent_state(self):
        """Create an AgentState instance."""
        state = AgentState()
        state.phase = AgentPhase.EXECUTE
        state.execution_plan = [
            {"step": 1, "action": "收集信息"},
            {"step": 2, "action": "执行任务"},
        ]
        return state
    
    @pytest.fixture
    def session_memory(self):
        """Create a SessionMemory instance."""
        memory = SessionMemory()
        memory.current_task = "测试任务"
        memory.current_phase = "EXECUTE"
        return memory
    
    @pytest.fixture
    def large_context(self):
        """Create a large context that triggers compression."""
        context = []
        for i in range(50):
            context.append({
                "role": "user",
                "content": f"这是第 {i} 条用户消息，内容较长以增加 token 数量。" * 20
            })
            context.append({
                "role": "assistant",
                "content": f"这是第 {i} 条助手回复，内容较长以增加 token 数量。" * 20
            })
        return context
    
    @pytest.fixture
    def small_context(self):
        """Create a small context that doesn't trigger compression."""
        return [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助你的吗？"},
        ]
    
    def test_compressor_initialization(self, compressor):
        """Test ContextCompressor initialization with default values."""
        assert compressor.compression_enabled is not None
        assert compressor.compress_threshold > 0
        assert compressor.context_window_max > 0
        assert compressor.keep_rounds > 0
        assert compressor._compression_count == 0
    
    def test_compressor_custom_settings(self, compressor_enabled):
        """Test ContextCompressor initialization with custom settings."""
        assert compressor_enabled.compression_enabled is True
        assert compressor_enabled.compress_threshold == 1000
        assert compressor_enabled.context_window_max == 2000
        assert compressor_enabled.keep_rounds == 5
    
    @pytest.mark.asyncio
    async def test_compress_if_needed_disabled(self, compressor_disabled, small_context):
        """Test that compression is skipped when disabled."""
        system_prompt = "测试系统提示"
        
        result_context, stats = await compressor_disabled.compress_if_needed(
            context=small_context,
            system_prompt=system_prompt,
        )
        
        assert result_context == small_context
        assert stats.original_tokens > 0
        assert stats.final_tokens == stats.original_tokens
        assert stats.levels_used == []
    
    @pytest.mark.asyncio
    async def test_compress_if_needed_below_threshold(self, compressor_enabled, small_context):
        """Test that compression is skipped when below threshold."""
        system_prompt = "测试系统提示"
        
        result_context, stats = await compressor_enabled.compress_if_needed(
            context=small_context,
            system_prompt=system_prompt,
        )
        
        assert result_context == small_context
        assert stats.original_tokens > 0
        assert stats.final_tokens == stats.original_tokens
        assert stats.levels_used == []
    
    @pytest.mark.asyncio
    async def test_compress_if_needed_triggers_l1(self, compressor_enabled, large_context):
        """Test that L1 compression is triggered when above threshold."""
        system_prompt = "测试系统提示"
        
        result_context, stats = await compressor_enabled.compress_if_needed(
            context=large_context,
            system_prompt=system_prompt,
        )
        
        assert len(result_context) < len(large_context)
        assert stats.original_tokens > compressor_enabled.compress_threshold
        assert stats.final_tokens < stats.original_tokens
        assert "L1" in stats.levels_used
        assert stats.compression_count == 1
    
    @pytest.mark.asyncio
    async def test_compress_if_needed_with_callback(self, compressor_enabled, large_context, agent_state):
        """Test that update_memory_callback is called when needed."""
        system_prompt = "测试系统提示"
        callback_called = []
        
        def callback():
            callback_called.append(True)
        
        with patch('src.agent.context.compression.compact_by_rounds') as mock_compact:
            mock_compact.return_value = large_context
            
            with patch('src.agent.context.compression.compress_context', new_callable=AsyncMock) as mock_compress:
                mock_compress.return_value = large_context
                
                with patch('src.agent.context.compression.estimate_context_tokens') as mock_estimate:
                    mock_estimate.side_effect = [1500, 1500, 1500, 1500]
                    
                    await compressor_enabled.compress_if_needed(
                        context=large_context,
                        system_prompt=system_prompt,
                        agent_state=agent_state,
                        update_memory_callback=callback,
                    )
        
        assert len(callback_called) > 0
    
    @pytest.mark.asyncio
    async def test_compress_if_needed_with_iteration_id(self, compressor_enabled, large_context):
        """Test that transcript is saved when iteration_id is provided."""
        system_prompt = "测试系统提示"
        
        with patch('src.agent.context.compression.save_transcript') as mock_save:
            mock_save.return_value = "/path/to/transcript.jsonl"
            
            with patch('src.agent.context.compression.compact_by_rounds') as mock_compact:
                mock_compact.return_value = large_context
                
                with patch('src.agent.context.compression.estimate_context_tokens') as mock_estimate:
                    mock_estimate.side_effect = [1500, 500, 500]
                    
                    result_context, stats = await compressor_enabled.compress_if_needed(
                        context=large_context,
                        system_prompt=system_prompt,
                        iteration_id="test_iter",
                    )
        
        assert stats.transcript_path == "/path/to/transcript.jsonl"


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing functions."""
    
    def test_compact_by_rounds_still_works(self):
        """Test that compact_by_rounds function still works independently."""
        context = [
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "回复1"},
            {"role": "user", "content": "消息2"},
            {"role": "assistant", "content": "回复2"},
        ]
        
        result = compact_by_rounds(context, keep_rounds=1)
        
        assert len(result) > 0
        assert result[0]["role"] == "system"
    
    def test_emergency_compact_still_works(self):
        """Test that emergency_compact function still works independently."""
        context = [
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "回复1"},
            {"role": "user", "content": "消息2"},
            {"role": "assistant", "content": "回复2"},
        ]
        
        result = emergency_compact(context)
        
        assert len(result) > 0
        assert result[0]["role"] == "system"
    
    @pytest.mark.asyncio
    async def test_compress_context_still_works(self):
        """Test that compress_context function still works independently."""
        context = [
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "回复1"},
        ]
        
        result = await compress_context(context)
        
        assert len(result) > 0
    
    def test_estimate_context_tokens_still_works(self):
        """Test that estimate_context_tokens function still works independently."""
        context = [
            {"role": "user", "content": "测试消息"},
            {"role": "assistant", "content": "测试回复"},
        ]
        
        tokens = estimate_context_tokens(context, "系统提示")
        
        assert tokens > 0
        assert isinstance(tokens, int)
