# -*- coding: utf-8 -*-
"""
Tests for the slide detection algorithm in pitch.py.
Verifies detection of linear slides (glissandos) in continuous F0 arrays.
"""
import pytest
import numpy as np
from punkito_tabs_oracle.dsp.pitch import PitchTracker


class TestSlideDetection:
    """Tests for slide detection in pitch tracking."""

    def test_ascending_slide_detection(self):
        """Test detection of ascending pitch slide."""
        tracker = PitchTracker()
        
        # Create ascending slide: 100Hz to 150Hz
        f0 = np.array([100.0, 110.0, 120.0, 130.0, 140.0, 150.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 1
        start_frame, end_frame, midi_start, midi_end = slides[0]
        assert start_frame == 0
        assert end_frame == 5
        assert midi_end > midi_start  # Should be ascending in MIDI

    def test_descending_slide_detection(self):
        """Test detection of descending pitch slide."""
        tracker = PitchTracker()
        
        # Create descending slide: 200Hz to 100Hz
        f0 = np.array([200.0, 190.0, 180.0, 170.0, 160.0, 150.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 1
        start_frame, end_frame, midi_start, midi_end = slides[0]
        assert start_frame == 0
        assert end_frame == 5
        assert midi_end < midi_start  # Should be descending in MIDI

    def test_no_slide_static_frequency(self):
        """Test that static frequency does not produce slides."""
        tracker = PitchTracker()
        
        # Static frequency: all 100Hz
        f0 = np.array([100.0, 100.0, 100.0, 100.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 0

    def test_slide_interrupted_by_voicing_gap(self):
        """Test that voicing gaps interrupt slide detection."""
        tracker = PitchTracker()
        
        # Ascending slide with voicing gap in middle
        f0 = np.array([100.0, 110.0, 0.0, 130.0, 140.0], dtype=float)
        voiced_prob = np.array([1.0, 1.0, 0.0, 1.0, 1.0], dtype=float)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        # Should not detect a single slide because of the gap
        assert len(slides) == 0

    def test_below_minimum_duration(self):
        """Test that slides below minimum duration are not detected."""
        tracker = PitchTracker()
        
        # Very short slide (only 2 frames)
        f0 = np.array([100.0, 110.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 0

    def test_multiple_slides_in_sequence(self):
        """Test detection of multiple slides in sequence."""
        tracker = PitchTracker()
        
        # Two ascending slides separated by rest
        f0 = np.array(
            [100.0, 110.0, 120.0, 0.0, 0.0, 150.0, 160.0, 170.0],
            dtype=float
        )
        voiced_prob = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0], dtype=float)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        # Should detect two separate slides
        assert len(slides) == 2
        # First slide
        assert slides[0][0] == 0 and slides[0][1] == 2
        # Second slide
        assert slides[1][0] == 5 and slides[1][1] == 7

    def test_slide_midi_conversion(self):
        """Test that slide endpoints are correctly converted to MIDI."""
        tracker = PitchTracker()
        
        # Known frequencies: A4=440Hz (MIDI 69), C5=262Hz (MIDI 60)
        f0 = np.array([262.0, 300.0, 350.0, 400.0, 440.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 1
        _, _, midi_start, midi_end = slides[0]
        # Approximately MIDI 60 to 69
        assert 59 <= midi_start <= 61
        assert 68 <= midi_end <= 70

    def test_onset_detection_stops_slide(self):
        """Test that detected onsets stop slide continuation."""
        tracker = PitchTracker()
        
        f0 = np.array([100.0, 110.0, 120.0, 130.0], dtype=float)
        voiced_prob = np.ones_like(f0)
        # Onset at frame 2 interrupts the slide
        onsets = np.array([2])
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3, onsets=onsets)
        
        # Slide should end before the onset
        if len(slides) > 0:
            _, end_frame, _, _ = slides[0]
            assert end_frame < 2

    def test_is_monotonic_ramp_ascending(self):
        """Test _is_monotonic_ramp detection for ascending ramp."""
        tracker = PitchTracker()
        
        f0_segment = np.array([100.0, 110.0, 120.0, 130.0], dtype=float)
        voiced_segment = np.array([True, True, True, True], dtype=bool)
        
        result = tracker._is_monotonic_ramp(f0_segment, voiced_segment, direction="up")
        
        assert result == True

    def test_is_monotonic_ramp_descending(self):
        """Test _is_monotonic_ramp detection for descending ramp."""
        tracker = PitchTracker()
        
        f0_segment = np.array([130.0, 120.0, 110.0, 100.0], dtype=float)
        voiced_segment = np.array([True, True, True, True], dtype=bool)
        
        result = tracker._is_monotonic_ramp(f0_segment, voiced_segment, direction="down")
        
        assert result == True

    def test_empty_f0_array(self):
        """Test handling of empty F0 array."""
        tracker = PitchTracker()
        
        f0 = np.array([], dtype=float)
        voiced_prob = np.array([], dtype=float)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 0

    def test_all_unvoiced_frames(self):
        """Test handling when all frames are unvoiced."""
        tracker = PitchTracker()
        
        f0 = np.array([100.0, 110.0, 120.0, 130.0], dtype=float)
        voiced_prob = np.zeros_like(f0)
        
        slides = tracker.detect_slides(f0, voiced_prob, min_duration_frames=3)
        
        assert len(slides) == 0
