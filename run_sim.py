from robohome.world.world import World
from robohome.viewer.viewer import Camera

def main():
    # 1. Boot up the physics engine
    my_world = World()
    
    # 2. Boot up the graphics engine and hand it the physics world
    camera = Camera(my_world)
    
    print("Starting RoboHome Simulator...")
    print("Close the Pygame window to stop the simulation.")
    
    # 3. Keep drawing the screen until the user clicks the 'X' button
    running = True
    while running:
        running = camera.render()

if __name__ == "__main__":
    main()