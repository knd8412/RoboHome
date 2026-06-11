import pygame
from robohome.world.world import World
from robohome.world.grid import CellType

# UI Color Palette (RGB)
COLOR_FLOOR = (240, 240, 240)
COLOR_WALL = (50, 50, 50)
COLOR_DOOR_CLOSED = (139, 69, 19)
COLOR_DOOR_OPEN = (205, 133, 63)
COLOR_ROBOT = (0, 120, 255)
COLOR_GRID = (200, 200, 200)
COLOR_FACING = (255, 0, 0)

TILE_SIZE = 40  # Each grid cell will be 40x40 pixels

class Camera:
    """A 2D Pygame visualizer that renders the current state of the World."""
    
    def __init__(self, world: World):
        self.world = world
        self.width = world.grid.width * TILE_SIZE
        self.height = world.grid.height * TILE_SIZE
        
        # Initialize the Pygame engine and create the window
        pygame.init()
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("RoboHome Simulator")
        self.clock = pygame.time.Clock()

    def render(self) -> bool:
        """
        Draws the grid, walls, doors, and robot. 
        Returns False if the user closes the window, True otherwise.
        """
        # 1. Listen for window close events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return False
                
        # 2. Paint the base floor
        self.screen.fill(COLOR_FLOOR)
        
        # 3. Draw the architecture (Walls and Doors)
        for y in range(self.world.grid.height):
            for x in range(self.world.grid.width):
                cell = self.world.grid.get_cell(x, y)
                rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                
                if cell.cell_type == CellType.WALL:
                    pygame.draw.rect(self.screen, COLOR_WALL, rect)
                elif cell.cell_type == CellType.DOOR:
                    color = COLOR_DOOR_OPEN if cell.is_open else COLOR_DOOR_CLOSED
                    pygame.draw.rect(self.screen, color, rect)
                
                # Draw a faint grid outline for readability
                pygame.draw.rect(self.screen, COLOR_GRID, rect, 1)

        # 4. Draw the Robot
        rx = self.world.robot.position.x
        ry = self.world.robot.position.y
        center = (rx * TILE_SIZE + TILE_SIZE // 2, ry * TILE_SIZE + TILE_SIZE // 2)
        
        # Draw the robot body
        pygame.draw.circle(self.screen, COLOR_ROBOT, center, (TILE_SIZE // 2) - 6)
        
        # Draw a red line indicating which way the robot is facing
        facing = self.world.robot.facing
        offset = 15
        if facing == "north": end_pos = (center[0], center[1] - offset)
        elif facing == "south": end_pos = (center[0], center[1] + offset)
        elif facing == "east": end_pos = (center[0] + offset, center[1])
        elif facing == "west": end_pos = (center[0] - offset, center[1])
        
        pygame.draw.line(self.screen, COLOR_FACING, center, end_pos, 3)

        # 5. Push the drawing to the screen
        pygame.display.flip()
        
        # Cap the framerate at 30 FPS to save CPU
        self.clock.tick(30)
        return True