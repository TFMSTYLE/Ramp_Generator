# SPDX-FileCopyrightText: 2025-2026 The French Monkey
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Ramp",
    "author": "The French Monkey",
    "version": (1, 4, 7),
    "blender": (4, 2, 0),
    "location": "Sidebar > Ramp Generator (Shader, Geometry, Compositor, Texture Node Editors)",
    "description": "Generate color ramps.",
    "category": "Node",
    "license": "GPL-3.0-or-later",
}

import bpy
import random
import math
import colorsys
import os

try:
    from . import relay_updater
except ImportError:  # the Addon Collection has its own updates
    relay_updater = None

# ------------------------------
# Preset palettes
# ------------------------------

PRESET_PALETTES = {
    "Sunset": [[1, 0.2, 0, 1], [1, 0.5, 0, 1], [1, 0.8, 0.2, 1], [1, 1, 0.5, 1]],
    "Ocean": [[0, 0.2, 0.6, 1], [0, 0.5, 0.8, 1], [0.2, 0.8, 1, 1], [0.5, 1, 1, 1]],
    "Forest": [[0, 0.3, 0, 1], [0, 0.5, 0.2, 1], [0.2, 0.7, 0.3, 1], [0.5, 1, 0.5, 1]],
    "Candy": [[1, 0, 0, 1], [1, 0.5, 0, 1], [1, 0, 1, 1], [0, 1, 1, 1]],
    "Desert": [[0.9,0.7,0.5,1], [0.95,0.8,0.6,1], [1,0.9,0.7,1], [1,1,0.8,1]],
    "Neon": [[1,0,1,1], [0,1,1,1], [1,1,0,1], [0,1,0,1]],
    "Bubblegum": [[1,0.7,0.9,1], [0.8,0.6,1,1], [1,0.8,0.9,1], [0.9,0.9,1,1]],
    "Winter": [[0,0.2,0.5,1], [0,0.5,0.7,1], [0.5,0.7,1,1], [0.8,0.9,1,1]],
    "Spring": [[0.4,1,0.5,1], [0.7,1,0.7,1], [1,0.8,0.9,1], [1,1,0.8,1]],
    "Retro": [[1,0,0.5,1], [1,0.5,0,1], [1,1,0,1], [0.5,1,0,1], [0,1,0.5,1], [0,1,1,1], [0,0.5,1,1], [0.5,0,1,1], [1,0,1,1], [1,0.5,0.5,1], [1,0.8,0.2,1], [0.6,0.2,1,1]],
    "Earth": [[0.3,0.2,0.1,1], [0.4,0.3,0.15,1], [0.5,0.35,0.2,1], [0.6,0.4,0.25,1], [0.7,0.5,0.3,1], [0.75,0.55,0.35,1], [0.8,0.6,0.4,1], [0.85,0.65,0.45,1], [0.9,0.7,0.5,1], [0.95,0.75,0.55,1]],
    "Fire": [[1,0,0,1], [1,0.1,0,1], [1,0.2,0,1], [1,0.3,0,1], [1,0.4,0.1,1], [1,0.5,0.2,1], [1,0.6,0.3,1], [1,0.7,0.4,1], [1,0.8,0.5,1], [1,0.9,0.6,1]],
    "Pastel": [[1,0.3,0.4,1], [1,0.4,0.2,1], [1,0.5,0.1,1], [1,0.6,0.1,1], [0.9,1,0.2,1], [0.8,1,0.3,1], [0.7,1,0.4,1], [0.5,1,0.5,1], [0.3,1,0.6,1], [0.2,1,0.7,1], [0.1,0.8,1,1], [0.2,0.5,1,1]]
}

# ------------------------------
# Utility Functions
# ------------------------------

def has_selected_color_ramp(context):
    space = context.space_data
    if not (space and space.type == 'NODE_EDITOR' and space.edit_tree):
        return False
    node = space.edit_tree.nodes.active
    return bool(node and node.type == 'VALTORGB' and node.select)


def get_selected_color_ramp(context):
    """Return the active ColorRamp node only if it is selected."""
    space = context.space_data
    if not (space and space.type == 'NODE_EDITOR' and space.edit_tree):
        return None
    node = space.edit_tree.nodes.active
    if node is None or node.type != 'VALTORGB' or not node.select:
        return None
    return node

def reset_color_ramp(node):
    ramp = node.color_ramp
    while len(ramp.elements) > 1:
        ramp.elements.remove(ramp.elements[0])
        ramp.elements[0].position = 0.0
        ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)

def make_positions(num, randomize):
    if num <= 1:
        return [0.5]
    if randomize:
        return sorted(random.random() for _ in range(num))
    return [i / (num - 1) for i in range(num)]

def lerp_color(c1, c2, t):
    return (
        c1[0] + (c2[0] - c1[0]) * t,
        c1[1] + (c2[1] - c1[1]) * t,
        c1[2] + (c2[2] - c1[2]) * t,
        1.0
    )

# ------------------------------
# Palette builders
# ------------------------------

def build_random_colors(num):
    return [(random.random(), random.random(), random.random(), 1.0) for _ in range(num)]

def build_greyscale_colors(num, even=False):
    if even and num > 1:
        return [(v, v, v, 1.0) for v in (i / (num - 1) for i in range(num))]
    return [(v, v, v, 1.0) for v in (random.random() for _ in range(num))]

def build_stripes_colors(num):
    return [(0.0, 0.0, 0.0, 1.0) if i % 2 == 0 else (1.0, 1.0, 1.0, 1.0) for i in range(num)]


def build_complementary_colors(num_colors):
    if num_colors < 2:
        num_colors = 2

    def hsv_to_rgba(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return [r, g, b, 1.0]

    h_start = random.random()
    s_start = random.uniform(0.0, 1.0)
    v_start = random.uniform(0.0, 1.0)

    h_end = (h_start + 0.5) % 1.0
    s_end = s_start
    v_end = v_start

    colors = []
    for i in range(num_colors):
        t = i / (num_colors - 1)
        h = h_start + t * (h_end - h_start)
        h = h % 1.0
        s = s_start + t * (s_end - s_start)
        v = v_start + t * (v_end - v_start)
        colors.append(hsv_to_rgba(h, s, v))

    return colors

def build_colors_from_image_fast(image_path, num_colors):
    if not image_path:
        return build_random_colors(num_colors)

    try:
        img = bpy.data.images.load(image_path)
    except:
        return build_random_colors(num_colors)

    pixels = list(img.pixels)
    img.user_clear()
    bpy.data.images.remove(img)

    rgba_pixels = [pixels[i:i+4] for i in range(0, len(pixels), 4) if i+4 <= len(pixels)]
    if not rgba_pixels:
        return build_random_colors(num_colors)

    random.shuffle(rgba_pixels)

    selected_colors = []
    attempts = 0
    max_attempts = len(rgba_pixels) * 2

    while len(selected_colors) < num_colors and attempts < max_attempts:
        px = random.choice(rgba_pixels)
        r, g, b, a = px

        if a == 0:
            attempts += 1
            continue

        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s < 0.01 and v > 0.99:
            attempts += 1
            continue

        duplicate = False
        for cr in selected_colors:
            if abs(cr[0]-r) < 0.02 and abs(cr[1]-g) < 0.02 and abs(cr[2]-b) < 0.02:
                duplicate = True
                break
        if duplicate:
            attempts += 1
            continue

        selected_colors.append([r, g, b, a])
        attempts += 1

    if len(selected_colors) < num_colors:
        selected_colors += build_random_colors(num_colors - len(selected_colors))

    return selected_colors[:num_colors]

# ------------------------------
# Palette Source
# ------------------------------

def generate_palette(num_colors, palette_type, preset_name=None, image_path=None, even_greys=False):
    if palette_type == 'COMPLEMENTARY':
        colors = build_complementary_colors(num_colors)
    elif palette_type == 'RANDOM':
        colors = build_random_colors(num_colors)
    elif palette_type == 'GREYSCALE':
        colors = build_greyscale_colors(num_colors, even_greys)
    elif palette_type == 'STRIPES':
        colors = build_stripes_colors(num_colors)
    elif palette_type == 'PRESET':
        preset = PRESET_PALETTES.get(preset_name or "", [])
        if not preset:
            colors = build_random_colors(num_colors)
        else:
            out = []
            while len(out) < num_colors:
                for c in preset:
                    if len(out) < num_colors:
                        out.append((c[0], c[1], c[2], 1.0))
            colors = out
    elif palette_type == 'CUSTOM':
        colors = build_colors_from_image_fast(image_path, num_colors)
    else:
        colors = build_random_colors(num_colors)

    return [ (c[0], c[1], c[2], 1.0) for c in colors ]

def generate_ramp(node, num_colors, palette_type, random_positions, preset_name=None, image_path=None):
    if node is None or node.type != 'VALTORGB':
        return
    positions = make_positions(num_colors, random_positions)
    colors = generate_palette(num_colors, palette_type, preset_name, image_path, even_greys=not random_positions)

    reset_color_ramp(node)
    ramp = node.color_ramp
    ramp.elements[0].position = positions[0]
    ramp.elements[0].color = colors[0]
    for i in range(1, num_colors):
        e = ramp.elements.new(positions[i])
        e.position = positions[i]
        e.color = colors[i]

# ------------------------------
# Operator
# ------------------------------

class NODE_OT_generate_ramp(bpy.types.Operator):
    bl_idname = "node.generate_ramp"
    bl_label = "Generate Ramp"
    bl_description = "Generate a color ramp based on the selected settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return has_selected_color_ramp(context)

    def execute(self, context):
        node = get_selected_color_ramp(context)
        if not node:
            self.report({'WARNING'}, "Select a ColorRamp node")
            return {'CANCELLED'}

        s = context.scene.ramp_gen_settings

        generate_ramp(
            node,
            s.num_colors,
            s.palette_type,
            s.random_positions,
            s.preset_name,
            s.custom_image_path
        )
        return {'FINISHED'}

# ------------------------------
# Properties
# ------------------------------

class RampGenSettings(bpy.types.PropertyGroup):
    palette_type: bpy.props.EnumProperty(
        name="Palette Source",
        items=[
            ('COMPLEMENTARY', "Complementary", "complementary color scheme"),
            ('RANDOM', "Random", "Random colors"),
            ('GREYSCALE', "Greyscale", "Even greys from black to white, or random greys with Random Position on"),
            ('STRIPES', "Stripes", "black and white stripes"),
            ('PRESET', "Preset", "Use a predefined palette"),
            ('CUSTOM', "Custom Image", "Sample from an image file"),
        ],
        default='COMPLEMENTARY'
    )
    preset_name: bpy.props.EnumProperty(
        name="Preset Palette",
        items=[(k, k, "") for k in PRESET_PALETTES.keys()],
        default=list(PRESET_PALETTES.keys())[0] if PRESET_PALETTES else ""
    )
    num_colors: bpy.props.IntProperty(
        name="Number of Colors",
        default=5,
        min=2,
        max=32,
        soft_min=2,
        soft_max=32,
        description="How many ramp stops to generate"
    )
    random_positions: bpy.props.BoolProperty(
        name="Random Position",
        default=False,
        description="Randomize color stop positions"
    )
    custom_image_path: bpy.props.StringProperty(
        name="Custom Image",
        subtype='FILE_PATH',
        description="Image file to sample colors from"
    )

# ------------------------------
# UI
# ------------------------------

class NODE_PT_ramp_generator(bpy.types.Panel):
    bl_label = "Ramp"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Ramp'

    def draw(self, context):
        if relay_updater:
            relay_updater.draw(self.layout)
        layout = self.layout
        s = context.scene.ramp_gen_settings

        layout.operator("node.generate_ramp", icon="COLOR")

        layout.prop(s, "palette_type", text="Palette Source")
        if s.palette_type == 'PRESET':
            layout.prop(s, "preset_name", text="Preset")
        elif s.palette_type == 'CUSTOM':
            layout.prop(s, "custom_image_path", text="Image")

        layout.prop(s, "num_colors", slider=True)
        layout.prop(s, "random_positions", text="Random Position")

        if not has_selected_color_ramp(context):
            col = layout.column()
            col.enabled = False
            col.label(text="Select a ColorRamp node to enable Generate")

# ------------------------------
# Registration
# ------------------------------

classes = (
    RampGenSettings,
    NODE_OT_generate_ramp,
    NODE_PT_ramp_generator,
)

def register():
    if relay_updater:
        relay_updater.register("blender-ramp")
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ramp_gen_settings = bpy.props.PointerProperty(type=RampGenSettings)

def unregister():
    if relay_updater:
        relay_updater.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ramp_gen_settings

if __name__ == "__main__":
    register()
