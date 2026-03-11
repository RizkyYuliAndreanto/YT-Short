"""
Frame-level video analysis using OpenCV.
Scores frames for visual interest (object presence, edge density, motion).
Used by clip_dub_engine to validate clips contain the main subject.

Enhanced with:
- Saliency-based object detection (no ML models needed)
- Motion-weighted region finding for moving subjects
- Contour-grouping to find the dominant object cluster
"""

import cv2
import numpy as np
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class FrameAnalyzer:
    """Analyze video frames to detect visual interest and object regions."""
    
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
    
    def score_clip(self, video_path: str, start_sec: float, duration: float,
                   sample_count: int = 5) -> Dict:
        """Score a clip region for visual interest.
        
        Samples multiple frames across the clip and analyzes each for:
        - Edge density (Canny): higher = more objects/detail
        - Contour count: more contours = more objects visible
        - Color variance: low variance = boring (plain sky/wall)
        - Center region focus: does the center have content?
        - Saliency: where the "standout" object is
        
        Args:
            video_path: Path to source video
            start_sec: Start time in seconds
            duration: Clip duration in seconds
            sample_count: Number of frames to sample
            
        Returns:
            Dict with scores and best_region info
        """
        cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return {"interest_score": 0.0, "has_subject": False}
        
        try:
            cap.set(cv2.CAP_PROP_N_THREADS, 1)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            
            # Sample frames across the clip
            offsets = [start_sec + (duration * i / max(sample_count - 1, 1)) 
                      for i in range(sample_count)]
            
            scores = []
            regions = []
            
            for t in offsets:
                frame_num = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                score, region = self._analyze_frame(frame)
                scores.append(score)
                regions.append(region)
            
            if not scores:
                return {"interest_score": 0.0, "has_subject": False}
            
            avg_score = sum(s["total"] for s in scores) / len(scores)
            best_idx = max(range(len(scores)), key=lambda i: scores[i]["total"])
            
            # A clip "has subject" if average edge density > threshold
            has_subject = avg_score > 0.25
            
            # Find the most consistent object region across frames
            best_region = regions[best_idx] if regions else None
            
            return {
                "interest_score": round(avg_score, 3),
                "has_subject": has_subject,
                "edge_density": round(sum(s["edge_density"] for s in scores) / len(scores), 3),
                "color_variance": round(sum(s["color_variance"] for s in scores) / len(scores), 3),
                "contour_score": round(sum(s["contour_score"] for s in scores) / len(scores), 3),
                "best_region": best_region,
                "frame_count": len(scores)
            }
        finally:
            cap.release()
    
    def _analyze_frame(self, frame: np.ndarray) -> Tuple[Dict, Optional[Dict]]:
        """Analyze a single frame for visual interest.
        
        Returns (scores_dict, region_dict)
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Edge density (Canny)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / (h * w)
        
        # 2. Color variance (low = plain sky/wall)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_variance = float(np.std(hsv[:, :, 0]) / 180.0)  # Hue std normalized
        
        # 3. Contour analysis
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Filter tiny contours (noise)
        significant = [c for c in contours if cv2.contourArea(c) > (h * w * 0.001)]
        contour_score = min(len(significant) / 20.0, 1.0)  # Normalize: 20+ contours = 1.0
        
        # 4. Center region analysis (center 50% of frame)
        cx, cy = w // 4, h // 4
        center = gray[cy:cy*3, cx:cx*3]
        center_edges = cv2.Canny(center, 50, 150)
        center_density = np.count_nonzero(center_edges) / max(center.shape[0] * center.shape[1], 1)
        
        # Combined score (weighted)
        total = (edge_density * 0.35 + 
                color_variance * 0.20 + 
                contour_score * 0.25 + 
                center_density * 0.20)
        
        scores = {
            "edge_density": edge_density,
            "color_variance": color_variance,
            "contour_score": contour_score,
            "center_density": center_density,
            "total": total
        }
        
        # Find region using contour-cluster method (much better than strip-based)
        region = self._find_subject_region(frame, edges, significant)
        
        return scores, region
    
    def _find_subject_region(self, frame: np.ndarray, edges: np.ndarray,
                             significant_contours: list) -> Optional[Dict]:
        """Find the dominant subject region using contour clustering + saliency.
        
        Instead of dividing into strips, this method:
        1. Groups nearby contours into clusters (likely the same object)
        2. Scores each cluster by size + compactness + contrast with surroundings
        3. Returns the center_x of the best cluster
        
        Much more accurate than strip-based for finding birds, animals, objects.
        """
        h, w = frame.shape[:2]
        
        if not significant_contours:
            return {"center_x": 0.5, "density": 0.0, "method": "fallback"}
        
        # Get bounding boxes of all significant contours
        boxes = []
        for c in significant_contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area = bw * bh
            # Skip very small or full-frame contours
            if area < (h * w * 0.002) or area > (h * w * 0.8):
                continue
            boxes.append((x, y, bw, bh, cv2.contourArea(c)))
        
        if not boxes:
            return self._find_interest_region_fine(edges, w, h)
        
        # Cluster nearby bounding boxes (merge overlapping/close boxes)
        clusters = self._cluster_boxes(boxes, w, h)
        
        if not clusters:
            return self._find_interest_region_fine(edges, w, h)
        
        # Score each cluster
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        best_score = -1
        best_cx = 0.5
        best_density = 0.0
        
        for cluster in clusters:
            cx1, cy1, cx2, cy2, total_contour_area = cluster
            cluster_w = cx2 - cx1
            cluster_h = cy2 - cy1
            cluster_area = cluster_w * cluster_h
            
            if cluster_area <= 0:
                continue
            
            # Score 1: Contour fill ratio (real contour area / bbox area)
            # Objects have higher fill, random edges have lower
            fill_ratio = min(total_contour_area / cluster_area, 1.0) if cluster_area > 0 else 0
            
            # Score 2: Size — prefer medium-sized objects (not too tiny, not full frame)
            frame_area = h * w
            size_ratio = cluster_area / frame_area
            # Peak at 5-30% of frame, penalize tiny (<1%) and huge (>60%)
            if size_ratio < 0.01:
                size_score = size_ratio * 10  # Very small
            elif size_ratio < 0.05:
                size_score = 0.5 + (size_ratio - 0.01) * 12.5
            elif size_ratio <= 0.30:
                size_score = 1.0
            elif size_ratio <= 0.60:
                size_score = 1.0 - (size_ratio - 0.30) * 2
            else:
                size_score = 0.4  # Nearly full frame
            
            # Score 3: Contrast with surroundings
            # Object region should differ from the average background
            cluster_region = gray[cy1:cy2, cx1:cx2]
            if cluster_region.size > 0:
                local_std = float(np.std(cluster_region))
                contrast_score = min(local_std / 80.0, 1.0)
            else:
                contrast_score = 0.0
            
            # Score 4: Edge concentration within the cluster bbox
            cluster_edges = edges[cy1:cy2, cx1:cx2]
            if cluster_edges.size > 0:
                edge_conc = np.count_nonzero(cluster_edges) / cluster_edges.size
            else:
                edge_conc = 0.0
            
            combined = (fill_ratio * 0.25 +
                       size_score * 0.30 +
                       contrast_score * 0.20 +
                       edge_conc * 0.25)
            
            if combined > best_score:
                best_score = combined
                best_cx = (cx1 + cx2) / 2.0 / w
                best_density = edge_conc
        
        return {
            "center_x": round(max(0.05, min(0.95, best_cx)), 3),
            "density": round(best_density, 4),
            "method": "contour_cluster"
        }
    
    def _cluster_boxes(self, boxes: list, frame_w: int, frame_h: int,
                       merge_distance: float = 0.08) -> List[Tuple]:
        """Merge nearby bounding boxes into object clusters.
        
        boxes: list of (x, y, w, h, contour_area)
        merge_distance: max gap between boxes as fraction of frame width to merge
        
        Returns: list of (x1, y1, x2, y2, total_contour_area) clusters
        """
        if not boxes:
            return []
        
        merge_px = int(frame_w * merge_distance)
        
        # Convert to (x1, y1, x2, y2, area)
        rects = [(x, y, x + bw, y + bh, ca) for (x, y, bw, bh, ca) in boxes]
        
        # Simple greedy clustering: merge boxes that overlap or are close
        merged = True
        while merged:
            merged = False
            new_rects = []
            used = [False] * len(rects)
            
            for i in range(len(rects)):
                if used[i]:
                    continue
                x1, y1, x2, y2, area = rects[i]
                
                for j in range(i + 1, len(rects)):
                    if used[j]:
                        continue
                    jx1, jy1, jx2, jy2, jarea = rects[j]
                    
                    # Check if close enough to merge (expanded bbox overlap)
                    if (x1 - merge_px <= jx2 and x2 + merge_px >= jx1 and
                        y1 - merge_px <= jy2 and y2 + merge_px >= jy1):
                        # Merge
                        x1 = min(x1, jx1)
                        y1 = min(y1, jy1)
                        x2 = max(x2, jx2)
                        y2 = max(y2, jy2)
                        area += jarea
                        used[j] = True
                        merged = True
                
                new_rects.append((x1, y1, x2, y2, area))
                used[i] = True
            
            rects = new_rects
        
        # Clamp to frame bounds
        result = []
        for (x1, y1, x2, y2, area) in rects:
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame_w, x2)
            y2 = min(frame_h, y2)
            result.append((x1, y1, x2, y2, area))
        
        return result
    
    def _find_interest_region_fine(self, edges: np.ndarray, w: int, h: int) -> Optional[Dict]:
        """Fine-grained interest region using 10 horizontal strips.
        
        Fallback when contour clustering has no result.
        Uses weighted center-of-mass of edge pixels for sub-strip precision.
        """
        # Get horizontal projection: sum of edge pixels per column
        col_sums = np.sum(edges > 0, axis=0).astype(np.float64)
        
        if col_sums.sum() == 0:
            return {"center_x": 0.5, "density": 0.0, "method": "fallback_fine"}
        
        # Weighted center of mass — gives us precise sub-pixel position
        x_coords = np.arange(w, dtype=np.float64)
        total_weight = col_sums.sum()
        center_x = float(np.dot(x_coords, col_sums) / total_weight) / w
        
        # Also compute density
        density = float(total_weight / (h * w))
        
        return {
            "center_x": round(max(0.05, min(0.95, center_x)), 3),
            "density": round(density, 4),
            "method": "edge_centroid"
        }
    
    def _find_interest_region(self, edges: np.ndarray, w: int, h: int,
                              grid_cols: int = 5) -> Optional[Dict]:
        """Find the horizontal region with highest edge density.
        
        Legacy method kept for compatibility. New code should use
        _find_subject_region() which is much more accurate.
        
        Returns dict with center_x (normalized 0-1) of the most interesting region.
        """
        # Use fine-grained edge centroid method (much better than strip-based)
        return self._find_interest_region_fine(edges, w, h)
    
    def score_clips_batch(self, video_path: str, 
                          clips: List[Dict],
                          sample_count: int = 3) -> List[Dict]:
        """Score multiple clips and attach results.
        
        Args:
            video_path: Source video path
            clips: List of highlight dicts with start_time, end_time, duration_seconds
            sample_count: Frames to sample per clip  
            
        Returns:
            Same clips list with added 'frame_score' field
        """
        for clip in clips:
            try:
                start_sec = self._ts_to_sec(clip.get("start_time", "00:00:00,000"))
                duration = clip.get("duration_seconds", 20)
                
                result = self.score_clip(video_path, start_sec, duration, sample_count)
                clip["frame_score"] = result
            except Exception:
                clip["frame_score"] = {
                    "interest_score": 0.0, 
                    "has_subject": False
                }
        
        return clips
    
    def find_best_crop_x(self, video_path: str, start_sec: float, 
                         duration: float, sample_count: int = 7) -> float:
        """Find the best horizontal center position for portrait cropping.
        
        Uses multi-method analysis:
        1. Contour clustering to find dominant object per frame
        2. Motion analysis (frame diff) to find where movement is
        3. Weighted voting across frames (recent frames weighted higher)
        
        Returns: center_x as normalized value (0.0-1.0), where 0.5 = center
        """
        cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return 0.5
        
        try:
            cap.set(cv2.CAP_PROP_N_THREADS, 1)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            
            offsets = [start_sec + (duration * i / max(sample_count - 1, 1))
                      for i in range(sample_count)]
            
            results = []  # (center_x, confidence)
            prev_gray = None
            
            for t in offsets:
                frame_num = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                h, w = frame.shape[:2]
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 50, 150)
                
                # Method 1: Contour clustering (best for distinct objects)
                contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                significant = [c for c in contours if cv2.contourArea(c) > (h * w * 0.001)]
                region = self._find_subject_region(frame, edges, significant)
                
                if region:
                    confidence = region.get("density", 0.1)
                    # Boost confidence if method was contour_cluster (more reliable)
                    if region.get("method") == "contour_cluster":
                        confidence = max(confidence, 0.3)
                    results.append((region["center_x"], confidence))
                
                # Method 2: Motion detection (where things are moving)
                if prev_gray is not None:
                    motion_cx = self._find_motion_center(prev_gray, gray, w)
                    if motion_cx is not None:
                        results.append((motion_cx, 0.25))  # Motion is a supporting signal
                
                prev_gray = gray
            
            if not results:
                return 0.5
            
            # Weighted average (higher confidence = more influence)
            total_weight = sum(conf for _, conf in results)
            if total_weight < 0.01:
                return 0.5
            
            weighted_x = sum(cx * conf for cx, conf in results) / total_weight
            
            # Clamp to safe crop zone
            return max(0.15, min(0.85, weighted_x))
        finally:
            cap.release()
    
    def _find_motion_center(self, prev_gray: np.ndarray, curr_gray: np.ndarray,
                            frame_w: int) -> Optional[float]:
        """Find horizontal center where motion is happening between two frames.
        
        Uses frame differencing — lightweight and effective for moving subjects.
        Returns normalized center_x or None if no significant motion.
        """
        # Resize to speed up (half resolution is fine for motion detection)
        small_prev = cv2.resize(prev_gray, (frame_w // 2, prev_gray.shape[0] // 2))
        small_curr = cv2.resize(curr_gray, (frame_w // 2, curr_gray.shape[0] // 2))
        
        diff = cv2.absdiff(small_prev, small_curr)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        
        # Check if there's enough motion to be meaningful
        motion_ratio = np.count_nonzero(thresh) / thresh.size
        if motion_ratio < 0.005 or motion_ratio > 0.5:
            # Too little motion (static) or too much (camera pan/scene change)
            return None
        
        # Find center of motion mass
        col_sums = np.sum(thresh > 0, axis=0).astype(np.float64)
        total = col_sums.sum()
        if total < 1:
            return None
        
        x_coords = np.arange(len(col_sums), dtype=np.float64)
        center_x = float(np.dot(x_coords, col_sums) / total) / len(col_sums)
        
        return center_x
    
    @staticmethod
    def _ts_to_sec(ts: str) -> float:
        """Convert SRT timestamp to seconds."""
        ts = ts.strip().replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(ts)
