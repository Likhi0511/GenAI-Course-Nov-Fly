"""
Simple Pillow (PIL) Image Creation Demo
Perfect for teaching students basic image manipulation concepts
"""

from PIL import Image, ImageDraw, ImageFont
import os


def create_simple_colored_image():
    """Demo 1: Create a basic colored rectangle"""
    print("Creating a simple colored image...")

    # Create a 400x300 image with a sky blue background
    img = Image.new('RGB', (400, 300), color='skyblue')
    img.save('outputs/01_simple_colored.png')
    print("✓ Saved: 01_simple_colored.png")


def create_gradient_image():
    """Demo 2: Create a gradient effect"""
    print("\nCreating a gradient image...")

    width, height = 400, 300
    img = Image.new('RGB', (width, height))

    # Create a horizontal gradient from red to blue
    for x in range(width):
        # Calculate color transition
        red = int(255 * (1 - x / width))
        blue = int(255 * (x / width))

        # Draw a vertical line for each x position
        for y in range(height):
            img.putpixel((x, y), (red, 0, blue))

    img.save('outputs/02_gradient.png')
    print("✓ Saved: 02_gradient.png")


def create_shapes_image():
    """Demo 3: Draw basic shapes"""
    print("\nCreating an image with shapes...")

    # Create a white canvas
    img = Image.new('RGB', (400, 300), color='white')
    draw = ImageDraw.Draw(img)

    # Draw a rectangle (border)
    draw.rectangle([50, 50, 150, 150], outline='red', width=3)

    # Draw a filled rectangle
    draw.rectangle([200, 50, 300, 150], fill='green', outline='darkgreen', width=2)

    # Draw a circle (ellipse with equal dimensions)
    draw.ellipse([50, 180, 150, 280], fill='blue', outline='darkblue', width=2)

    # Draw a filled ellipse
    draw.ellipse([200, 180, 350, 280], fill='yellow', outline='orange', width=2)

    img.save('outputs/03_shapes.png')
    print("✓ Saved: 03_shapes.png")


def create_text_image():
    """Demo 4: Add text to an image"""
    print("\nCreating an image with text...")

    # Create a light background
    img = Image.new('RGB', (500, 200), color='lightyellow')
    draw = ImageDraw.Draw(img)

    # Add a border
    draw.rectangle([0, 0, 499, 199], outline='orange', width=3)

    # Add text (using default font)
    text = "Hello, Students!"
    draw.text((150, 80), text, fill='darkblue')

    # Add more text
    subtitle = "Learning Pillow is fun!"
    draw.text((130, 120), subtitle, fill='green')

    img.save('outputs/04_text.png')
    print("✓ Saved: 04_text.png")


def create_pattern_image():
    """Demo 5: Create a simple pattern"""
    print("\nCreating a pattern image...")

    img = Image.new('RGB', (400, 400), color='white')
    draw = ImageDraw.Draw(img)

    # Create a checkerboard pattern
    square_size = 50
    colors = ['purple', 'pink']

    for row in range(8):
        for col in range(8):
            # Alternate colors
            color = colors[(row + col) % 2]
            x1 = col * square_size
            y1 = row * square_size
            x2 = x1 + square_size
            y2 = y1 + square_size

            draw.rectangle([x1, y1, x2, y2], fill=color)

    img.save('outputs/05_pattern.png')
    print("✓ Saved: 05_pattern.png")


def create_combined_demo():
    """Demo 6: Combine multiple concepts"""
    print("\nCreating a combined demonstration...")

    # Create canvas
    img = Image.new('RGB', (600, 400), color='lightblue')
    draw = ImageDraw.Draw(img)

    # Draw a sun
    draw.ellipse([450, 50, 550, 150], fill='yellow', outline='orange', width=3)

    # Draw grass
    draw.rectangle([0, 300, 600, 400], fill='lightgreen')

    # Draw a simple house
    # House body
    draw.rectangle([150, 200, 350, 300], fill='beige', outline='brown', width=2)

    # Roof
    draw.polygon([(150, 200), (250, 120), (350, 200)], fill='darkred', outline='maroon')

    # Door
    draw.rectangle([220, 230, 280, 300], fill='brown', outline='black', width=2)

    # Window
    draw.rectangle([170, 220, 210, 260], fill='lightblue', outline='black', width=2)

    # Add welcoming text
    draw.text((200, 350), "Welcome Home!", fill='darkgreen')

    img.save('outputs/06_combined_scene.png')
    print("✓ Saved: 06_combined_scene.png")


def main():
    """Run all demonstrations"""
    print("=" * 50)
    print("PILLOW IMAGE CREATION DEMONSTRATION")
    print("=" * 50)

    # Create output directory if it doesn't exist
    os.makedirs('outputs', exist_ok=True)

    # Run all demos
    create_simple_colored_image()
    create_gradient_image()
    create_shapes_image()
    create_text_image()
    create_pattern_image()
    create_combined_demo()

    print("\n" + "=" * 50)
    print("All images created successfully!")
    print("Check the outputs folder for the results.")
    print("=" * 50)


if __name__ == "__main__":
    main()