import heapq
from typing import List, Optional, Tuple
from robohome.world.world import World

def shortest_path(world: World, start: Tuple[int, int], goal: Tuple[int, int]) -> Optional[List[Tuple[int, int]]]:
    """Finds the shortest valid path between two tiles using A* search."""
    start_x, start_y = start
    goal_x, goal_y = goal
    
    # Queue to prioritize the most promising tiles
    open_set = []
    heapq.heappush(open_set, (0, start))
    
    came_from = {}
    g_score = {start: 0}
    
    def heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        """Calculates Manhattan distance (grid steps)."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    while open_set:
        _, current = heapq.heappop(open_set)
        
        if current == goal:
            # Destination reached; reconstruct path backwards
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start)
            path.reverse()
            return path
            
        curr_x, curr_y = current
        
        # Check North, East, South, West neighbors
        for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
            neighbor = (curr_x + dx, curr_y + dy)
            cell = world.grid.get_cell(neighbor[0], neighbor[1])
            
            # Skip walls, closed doors, and out-of-bounds tiles
            if not cell or not cell.is_walkable:
                continue
                
            tentative_g = g_score[current] + 1
            
            # Record this path if it's the fastest way found so far
            if neighbor not in g_score or tentative_g < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f_score = tentative_g + heuristic(neighbor, goal)
                heapq.heappush(open_set, (f_score, neighbor))
                
    return None # Path is completely blocked