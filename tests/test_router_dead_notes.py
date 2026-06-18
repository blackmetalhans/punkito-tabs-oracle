# -*- coding: utf-8 -*-
"""
Tests for the refactored router with dead note handling.
Verifies that the Viterbi traceback never crashes with empty trellis.
"""
import pytest
from punkito_tabs_oracle.tab.router import FretboardRouter, State


class TestRouterDeadNotes:
    """Tests for dead note handling in the router."""

    def test_dead_notes_with_valid_midi(self):
        """Test that dead notes with valid MIDI values don't crash."""
        router = FretboardRouter()
        midi_seq = [28, 33, 45]
        articulation_seq = ["dead", "dead", "dead"]
        
        states, tab = router.route_from_midi(midi_seq, articulation_seq)
        
        assert len(states) == 3
        # All states should be unvoiced (dead) fallback states
        assert all(s.string is None and s.fret == -1 for s in states)
        assert all(s.articulation_type == "dead" for s in states)
        # Tab should render without error
        assert isinstance(tab, str)

    def test_mixed_articulation_normal_and_dead(self):
        """Test mixed articulation types (normal and dead)."""
        router = FretboardRouter()
        midi_seq = [28, 33, 45, 40]
        articulation_seq = ["normal", "dead", "normal", "dead"]
        
        states, tab = router.route_from_midi(midi_seq, articulation_seq)
        
        assert len(states) == 4
        # First state: normal articulation
        assert states[0].articulation_type == "normal"
        assert states[0].string is not None
        # Second state: dead articulation (fallback)
        assert states[1].articulation_type == "dead"
        assert states[1].string is None
        # Third state: normal articulation
        assert states[2].articulation_type == "normal"
        assert states[2].string is not None
        # Fourth state: dead articulation (fallback)
        assert states[3].articulation_type == "dead"
        assert states[3].string is None

    def test_high_midi_notes_out_of_range(self):
        """Test that high MIDI notes outside bass range are handled gracefully."""
        router = FretboardRouter()
        midi_seq = [100, 101, 102]
        
        states, tab = router.route_from_midi(midi_seq)
        
        assert len(states) == 3
        # All should be fallback rest states
        assert all(s.string is None and s.fret == -1 for s in states)
        # Tab should render
        assert isinstance(tab, str)

    def test_fast_track_alternating_notes_and_rests(self):
        """Test fast track simulation with alternating notes and rests."""
        router = FretboardRouter()
        midi_seq = [28, None, 28, None, 28, None, 28, None]
        
        states, tab = router.route_from_midi(midi_seq)
        
        assert len(states) == 8
        # Odd indices should be rests (None, -1)
        for i in range(0, 8, 2):
            assert states[i].string == 4 and states[i].fret == 0  # E open
            assert states[i + 1].string is None and states[i + 1].fret == -1  # Rest

    def test_transition_cost_with_dead_notes(self):
        """Test that transition costs to dead notes are neutral (0.0)."""
        router = FretboardRouter()
        
        # Normal to Normal
        u1 = State(string=4, fret=0, articulation_type="normal")
        v1 = State(string=3, fret=0, articulation_type="normal")
        cost1 = router._transition_cost(u1, v1)
        assert cost1 > 0  # Should have some cost (string change)
        
        # Normal to Dead
        u2 = State(string=4, fret=0, articulation_type="normal")
        v2 = State(string=None, fret=-1, articulation_type="dead")
        cost2 = router._transition_cost(u2, v2)
        assert cost2 == 0.0  # Should be neutral cost
        
        # Dead to Normal
        u3 = State(string=None, fret=-1, articulation_type="dead")
        v3 = State(string=4, fret=0, articulation_type="normal")
        cost3 = router._transition_cost(u3, v3)
        assert cost3 == 0.0  # Should be neutral cost

    def test_midi_candidates_with_dead_articulation(self):
        """Test that _midi_candidates returns fallback for dead articulation."""
        router = FretboardRouter()
        
        # Dead articulation should always return fallback rest state
        candidates = router._midi_candidates(50, articulation_type="dead")
        assert len(candidates) == 1
        assert candidates[0].string is None
        assert candidates[0].fret == -1
        assert candidates[0].articulation_type == "dead"

    def test_no_empty_trellis_collapse(self):
        """Verify that the dynamic programming matrix never collapses."""
        router = FretboardRouter()
        
        # Create a challenging sequence that could cause trellis collapse
        midi_seq = [None, 100, 101, 102, None, 28, None, 99, 100]
        articulation_seq = ["normal", "dead", "normal", "dead", "normal", "dead", "normal", "normal", "dead"]
        
        states, tab = router.route_from_midi(midi_seq, articulation_seq)
        
        # Should not crash and should return valid states
        assert len(states) == len(midi_seq)
        # All states should be valid (not None)
        assert all(isinstance(s, State) for s in states)
