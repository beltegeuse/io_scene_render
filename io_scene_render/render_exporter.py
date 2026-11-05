import bpy
import bmesh
import os
import math
from math import *
import mathutils
from mathutils import Vector
import shutil
import json
import re
import numpy as np

#render engine custom begin
class RendererRenderEngine(bpy.types.RenderEngine):
    bl_idname = 'Renderer_Renderer'
    bl_label = 'Renderer_Renderer'
    bl_use_preview = False
    bl_use_material = True
    bl_use_shading_nodes = False
    bl_use_shading_nodes_custom = False
    bl_use_texture_preview = True
    bl_use_texture = True
    

    def render(self, scene):
        self.report({'ERROR'}, "Use export function in Renderer panel.")
        
from bl_ui import properties_render
from bl_ui import properties_material

def compat_engine_sets():
    for module in (properties_render, properties_material):
        for member in dir(module):
            compat_engines = getattr(getattr(module, member), "COMPAT_ENGINES", None)
            if isinstance(compat_engines, set):
                yield compat_engines

# RendererRenderEngine itself is registered by auto_load
def register():
    for compat_engines in compat_engine_sets():
        compat_engines.add('Renderer_Renderer')

def unregister():
    for compat_engines in compat_engine_sets():
        compat_engines.discard('Renderer_Renderer')

exportedMaterials = list()

#Camera code:
#https://blender.stackexchange.com/questions/16472/how-can-i-get-the-cameras-projection-matrix
def measure(first, second):
    locx = second[0] - first[0]
    locy = second[1] - first[1]
    locz = second[2] - first[2]

    distance = sqrt((locx)**2 + (locy)**2 + (locz)**2)
    return distance

def export_camera(parent, scene):
    parent.report({'INFO'}, " Fetching camera..")
    cam_ob = bpy.context.scene.camera
    if cam_ob is None or cam_ob.type != 'CAMERA':
        parent.report({'ERROR'}, "No scene camera, aborting")
        parent.error_or_warning = True
        parent.fatal_error = True
        return None
    else:
        parent.report({'INFO'}, f"Exporting camera: {cam_ob.name} [{scene.render.resolution_x}x{scene.render.resolution_y}]")

        cameramatrix = cam_ob.matrix_world.copy()
        matrixTransposed = cameramatrix.transposed()
        up_point = matrixTransposed[1]

        from_point=cam_ob.matrix_world.col[3]
        at_point=cam_ob.matrix_world.col[2]
        at_point=at_point * -1
        at_point=at_point + from_point

        camera_dict = {}
        
        camera_dict["resolution"] = [
            scene.resolution_x,
            scene.resolution_y
        ]

        # https://blender.stackexchange.com/questions/14745/how-do-i-change-the-focal-length-of-a-camera-with-python
        fov = cam_ob.data.angle * 180 / math.pi
        camera_dict["vfov"] = fov * (scene.resolution_y/scene.resolution_x)
        
        if scene.dofLookAt is not None:
            camera_dict["fdist"] = measure(cam_ob.matrix_world.translation, scene.dofLookAt.matrix_world.translation)
            camera_dict["aperture"] = scene.lensradius
        else:
            camera_dict["fdist"] = 1.0

        camera_dict["transform"] = {
            "from" : [from_point.x, from_point.y, from_point.z],
            "at" : [at_point.x, at_point.y, at_point.z],
            "up" : [up_point[0],up_point[1],up_point[2]]
        }

        return (camera_dict, {
            "type" : "independent",
            "samples" : scene.spp
        })
        
def texture_might_exist(inputSlot):
    return len(inputSlot.links) > 0

def texture_copy(parent, node, filepath):
    fromFile = bpy.path.abspath(node.image.filepath)
    head, tail = os.path.split(fromFile)
    
    toFile = bpy.path.abspath(filepath + '/textures/' + tail)
    parent.report({'INFO'}, f"Copying texture: {fromFile} to {toFile}")
    if not os.path.exists(os.path.dirname(toFile)):
        os.makedirs(os.path.dirname(toFile))
    
    if not os.path.exists(fromFile):
        parent.report({'ERROR'}, f"Texture does not exist: {fromFile}. You might forget to unpack the file.")
        parent.error_or_warning = True
        parent.fatal_error = True
        return
    
    if os.path.realpath(fromFile) != os.path.realpath(toFile):
        if os.path.exists(toFile):
             parent.report({'WARNING'}, f"Texture already exist: {toFile}. Do not copy")
        else:
            shutil.copyfile(os.path.realpath(fromFile), os.path.realpath(toFile))

def only_value (parent, inputSlot):
    """Return value"""
    if(len(inputSlot.links) == 0):
        if type(inputSlot.default_value) == float:
            return inputSlot.default_value
        else: 
            return [inputSlot.default_value[0], 
                    inputSlot.default_value[1], 
                    inputSlot.default_value[2]]
  
    node = inputSlot.links[0].from_node # Take always the first link
              
    if node.bl_idname == "ShaderNodeRGB":
        return [
            node.outputs[0].default_value[0],
            node.outputs[0].default_value[1],
            node.outputs[0].default_value[2]
        ]
    
    parent.report({'WARNING'}, f"Texture are not supported for envmap: {node.bl_idname}.")
    parent.error_or_warning = True
    return [0.0, 0.0, 0.0]

def texture_or_value (parent, inputSlot, filepath, scale=1.0, is_normal_map = False):
    """Return BSDF information"""
    if(len(inputSlot.links) == 0):
        if type(inputSlot.default_value) == float:
            return inputSlot.default_value * scale
        else: 
            return [inputSlot.default_value[0] * scale, 
                    inputSlot.default_value[1] * scale, 
                    inputSlot.default_value[2] * scale]

    
    node = inputSlot.links[0].from_node # Take always the first link

    # Check if normal map, and get the node
    if node.bl_idname == "ShaderNodeNormalMap":
        parent.report({'WARNING'}, f"Detect normal map, Strength is ignored: {node.inputs['Strength'].default_value}")
        if len(node.inputs["Color"].links) > 0:
            node = node.inputs["Color"].links[0].from_node
        else:
            return {}
        

    parent.report({'INFO'}, f"Texture type: {node.bl_idname}")
    if node.bl_idname == "ShaderNodeTexChecker":
        parent.report({'INFO'}, " Detect checkerboard texture")
        # Checker board
        c1 = node.inputs[1].default_value
        c2 = node.inputs[2].default_value
        uv_scale = node.inputs[3].default_value
        return {
            "color1" : [c1[0], c1[1], c1[2]],
            "color2" : [c2[0], c2[1], c2[2]],
            "uv_scale" : [uv_scale / 2, uv_scale / 2],
            "scale" : scale,
            "type" : "checkerboard2d"
        }
    elif node.bl_idname == "ShaderNodeTexEnvironment":
        texture_copy(parent, node, filepath)
        return {
            "type" : "texture",
            "filename" : "textures/"+node.image.name,
        }
    elif node.bl_idname == "ShaderNodeTexImage":
        filename = os.path.split(node.image.filepath.replace("\\","//"))[1]
        parent.report({'INFO'}, f"Detect Texture image: {node.image.name} | {filename}") 
        texture_copy(parent, node, filepath)
        if len(node.inputs[0].links) > 0:
            parent.report({'INFO'}, f"Number links For Texture mapping: {len(node.inputs[0].links)}")

            # TODO: Assume mapping node for texture manipulation
            # TODO: Fix this later

            # nodeMapping = node.inputs[0].links[0].from_node
            # scale = nodeMapping.inputs[3].default_value
            # t = nodeMapping.inputs[1].default_value
            # r = nodeMapping.inputs[2].default_value #  order='XYZ'
            # translate = [t[0],t[1],t[2]]
            # scaleXYZ = [scale[0],scale[1],scale[2]]
            # rot_angles = [r[0],r[1],r[2]]
            # rot_anglesDegree = [math.degrees(r[0]) ,math.degrees(r[1]),math.degrees(r[2])]
            
            # TODO: Might not be standard mapping
            return {
                "type" : "texture",
                "filename" : "textures/"+filename,
                # "scale" : scaleXYZ,
                # "translate" : translate,
                # "rotation" : rot_angles,
                # "rotationDegree" : rot_anglesDegree,
                "gamma" : not is_normal_map,
                "scale" : scale
            }
        else:
            # Default export
            return {
                "type" : "texture",
                "filename" : "textures/"+filename,
                "gamma" : not is_normal_map,
                "scale" : scale
            }
    else:
        parent.report({'WARNING'}, f"Unsupported node export: {node.bl_idname} | default: {inputSlot.default_value} | {type(inputSlot.default_value)}")
        parent.error_or_warning = True
        if is_normal_map:
            return {
                "type" : "constant",
                "value" : [0, 0, 1]
            }
        else:
            if type(inputSlot.default_value) == float:
                return inputSlot.default_value * scale
            else: 
                return [inputSlot.default_value[0] * scale, 
                        inputSlot.default_value[1] * scale, 
                        inputSlot.default_value[2] * scale]
            

def export_material_node(parent, scene, mat, materialName, filepath):
    parent.report({'INFO'}, "Exporting material node type : " + mat.bl_idname)
    mat_data = {}
    if mat.bl_idname == 'ShaderNodeBsdfDiffuse':
        mat_data["type"] = "diffuse"
        mat_data["albedo"] = texture_or_value(parent, mat.inputs[0], filepath)
    elif mat.bl_idname == "ShaderNodeEmission":
        mat_data["type"] = "diffuse_light"
        scale = mat.inputs[1].default_value
        mat_data["radiance"] = texture_or_value(parent, mat.inputs[0], filepath, scale)
    elif mat.bl_idname == "ShaderNodeMixShader":
        fresnel = False
        if(len(mat.inputs[0].links) != 0):
            node = mat.inputs[0].links[0].from_node
            fresnel = (node.bl_idname == "ShaderNodeFresnel")
        # else blend
        if fresnel:
            mat_data["type"] = "fresnel_blend"
            fresnel_node = mat.inputs[0].links[0].from_node
            mat_data["eta"] = texture_or_value(parent, fresnel_node.inputs[0], filepath)
        else:
            mat_data["type"] = "blend"
            mat_data["alpha"] = texture_or_value(parent, mat.inputs[0], filepath)
        mat_data["matA"] = export_material_node(parent, scene, mat.inputs[2].links[0].from_node, materialName, filepath)
        mat_data["matB"] = export_material_node(parent, scene, mat.inputs[1].links[0].from_node, materialName, filepath)
    elif mat.bl_idname == "ShaderNodeBsdfGlass":
        mat_data["type"] = "dielectric"
        mat_data["ks"] = texture_or_value(parent, mat.inputs[0], filepath) # Color
        mat_data["roughness"] = mat.inputs[1].default_value     # Roughness
        mat_data["eta_int"] = mat.inputs[2].default_value       # IOR
        # TODO: Export IOR (texture - 1d)
    elif mat.bl_idname == "ShaderNodeBsdfGlossy" or mat.bl_idname == "ShaderNodeBsdfAnisotropic":
        mat_data["type"] = "metal"
        mat_data["ks"] = texture_or_value(parent, mat.inputs[0], filepath)
        mat_data["roughness"] = mat.inputs[1].default_value # roughness
    elif mat.bl_idname == "ShaderNodeBsdfPrincipled":
        parent.report({'WARNING'}, " Principled shader not fully supported")
        parent.error_or_warning = True
        # Export as diffuse
        local_material = {}
        if scene.improved_principled:
            # Examples of inputs:
            # Principled input: Base Color | default: <bpy_float[4], NodeSocketColor.default_value> | links: 1
            # Principled input: Metallic | default: 0.20000000298023224 | links: 0
            # Principled input: Roughness | default: 0.5 | links: 1
            # Principled input: IOR | default: 1.4500000476837158 | links: 0
            # Principled input: Alpha | default: 1.0 | links: 0
            # Principled input: Normal | default: <bpy_float[3], NodeSocketVector.default_value> | links: 1
            # Principled input: Weight | default: 0.0 | links: 0
            # Principled input: Diffuse Roughness | default: 0.0 | links: 0
            # Principled input: Subsurface Weight | default: 0.0 | links: 0
            # Principled input: Subsurface Radius | default: <bpy_float[3], NodeSocketVector.default_value> | links: 0
            # Principled input: Subsurface Scale | default: 0.05000000074505806 | links: 0
            # Principled input: Subsurface IOR | default: 1.399999976158142 | links: 0
            # Principled input: Subsurface Anisotropy | default: 0.0 | links: 0
            # Principled input: Specular IOR Level | default: 0.20000000298023224 | links: 0
            # Principled input: Specular Tint | default: <bpy_float[4], NodeSocketColor.default_value> | links: 0
            # Principled input: Anisotropic | default: 0.0 | links: 0
            # Principled input: Anisotropic Rotation | default: 0.0 | links: 0
            # Principled input: Tangent | default: <bpy_float[3], NodeSocketVector.default_value> | links: 0
            # Principled input: Transmission Weight | default: 0.0 | links: 0
            # Principled input: Coat Weight | default: 0.0 | links: 0
            # Principled input: Coat Roughness | default: 0.029999999329447746 | links: 0
            # Principled input: Coat IOR | default: 1.5 | links: 0
            # Principled input: Coat Tint | default: <bpy_float[4], NodeSocketColor.default_value> | links: 0
            # Principled input: Coat Normal | default: <bpy_float[3], NodeSocketVector.default_value> | links: 0
            # Principled input: Sheen Weight | default: 0.0 | links: 0
            # Principled input: Sheen Roughness | default: 0.5 | links: 0
            # Principled input: Sheen Tint | default: <bpy_float[4], NodeSocketColor.default_value> | links: 0
            # Principled input: Emission Color | default: <bpy_float[4], NodeSocketColor.default_value> | links: 0
            # Principled input: Emission Strength | default: 1.0 | links: 0
            # Principled input: Thin Film Thickness | default: 0.0 | links: 0
            # Principled input: Thin Film IOR | default: 1.3300000429153442 | links: 0
            parent.report({'INFO'}, " Using improved principled material export")
            # for input in mat.inputs:
            #     parent.report({'INFO'}, f" Principled input: {input.name} | default: {input.default_value} | links: {len(input.links)}")
            local_material["type"] = "blend"
            base_color = texture_or_value(parent, mat.inputs["Base Color"], filepath)
            local_material["alpha"] = texture_or_value(parent, mat.inputs["Metallic"], filepath)
            local_material["matA"] = {
                "type" : "metal",
                "ks" : base_color,
                "roughness" : texture_or_value(parent, mat.inputs["Roughness"], filepath),
                "specular": texture_or_value(parent, mat.inputs["Specular Tint"], filepath),
                "anisotropic": texture_or_value(parent, mat.inputs["Anisotropic"], filepath),
                "anisotropic_rotation": texture_or_value(parent, mat.inputs["Anisotropic Rotation"], filepath),
            }
            local_material["matB"] = {
                "type" : "diffuse",
                "albedo" : base_color
            }
            if mat.inputs["Transmission Weight"].default_value > 0.0:
                parent.error_or_warning = True
                parent.report({'WARNING'}, " Transmission not supported")
            
        else:
            local_material["type"] = "diffuse"
            local_material["albedo"] = texture_or_value(parent, mat.inputs[0], filepath)
        exported_normal = False
        if scene.export_normal_map: 
            # TODO: Export other parameters
            if texture_might_exist(mat.inputs["Normal"]):
                normal_map_params = texture_or_value(parent, mat.inputs["Normal"], filepath, is_normal_map = True)
                if len(normal_map_params) != 0:
                    # Normal map added if found
                    mat_data["type"] = "normal_map"
                    mat_data["normal_map"] = normal_map_params
                    mat_data["material"] = local_material
                    exported_normal = True
                else:
                    # Ignore normal map
                    parent.report({'WARNING'}, "Normal map ignored -- wrong node topology")
        if not exported_normal:
            mat_data = local_material
            
    else:
        parent.report({'WARNING'}, f"Wrong material: {materialName} | type: {mat.bl_idname}")
        parent.error_or_warning = True
        mat_data["type"] = "diffuse"

    # Give name 
    mat_data["name"] = materialName
    if not ("type" in mat_data):
        parent.report({'WARNING'}, f"Wrong material: {materialName} | type: {mat.bl_idname} | json: {mat_data}")
        parent.error_or_warning = True
        mat_data["type"] = "diffuse"
        mat_data["albedo"] = [0.8, 0.0, 0.8]
    return mat_data

def export_material(parent, scene, material, filepath):
    mats = []
    parent.report({'INFO'}, f'Exporting material named: {material.name}')
    if material.node_tree is not None:
        for node in material.node_tree.nodes:
            if node.type == "OUTPUT_MATERIAL":
                for input in node.inputs:
                    for node_links in input.links:
                        currentMaterial =  node_links.from_node
                        mats += [export_material_node(parent, scene, currentMaterial, material.name, filepath)]
    if len(mats) == 0:
        # The shapes reference this material by name: it has to exist in the scene file
        parent.report({'WARNING'}, f"Material without connected output: {material.name}, using a diffuse")
        parent.error_or_warning = True
        mats = [{"type" : "diffuse", "name" : material.name, "albedo" : [0.8, 0.8, 0.8]}]
    return mats

def read_mesh_triangles(mesh, nb_parts):
    """Read the triangle corners of an evaluated mesh as numpy arrays.

    Returns the loop index of each triangle corner (shape: nb_triangles x 3), the
    part of each triangle, and the per-loop positions / normals / uvs (uvs: None if
    the mesh has no UV layer). Adding 0.0 turns -0.0 into 0.0, so that equal values
    have equal bytes when welding the vertices.
    """
    nb_triangles = len(mesh.loop_triangles)
    triangle_loops = np.empty(nb_triangles * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", triangle_loops)
    triangle_materials = np.empty(nb_triangles, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", triangle_materials)

    nb_loops = len(mesh.loops)
    loop_vertices = np.empty(nb_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    vertex_positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", vertex_positions)
    positions = vertex_positions.reshape(-1, 3)[loop_vertices] + 0.0

    normals = np.empty(nb_loops * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", normals)
    normals = normals.reshape(-1, 3) + 0.0

    uvs = None
    uv_layer = next((layer for layer in mesh.uv_layers if layer.active_render), None)
    if uv_layer is not None:
        uvs = np.empty(nb_loops * 2, dtype=np.float32)
        uv_layer.uv.foreach_get("vector", uvs)
        uvs = uvs.reshape(-1, 2) + 0.0

    # Like Blender, an out of range material index uses the last material
    triangle_parts = np.clip(triangle_materials, 0, nb_parts - 1)
    return triangle_loops.reshape(-1, 3), triangle_parts, positions, normals, uvs

def write_ply(filepath, triangle_loops, positions, normals, uvs):
    """Write triangles as a binary PLY with welded vertices.

    A vertex is unique per (position, normal, uv). The renderers rely on it: they use
    the vertex indices of the faces to accumulate the tangents.
    """
    fields = [("position", "<f4", (3,)), ("normal", "<f4", (3,))]
    if uvs is not None:
        fields.append(("uv", "<f4", (2,)))
    vertex_type = np.dtype(fields)

    corners = triangle_loops.ravel()
    corner_vertices = np.empty(len(corners), dtype=vertex_type)
    corner_vertices["position"] = positions[corners]
    corner_vertices["normal"] = normals[corners]
    if uvs is not None:
        corner_vertices["uv"] = uvs[corners]

    # Weld, keeping the vertices in order of first use (better memory locality for the renderers)
    corner_bytes = corner_vertices.view(np.dtype((np.void, vertex_type.itemsize)))
    _, first_corner, unique_index = np.unique(corner_bytes, return_index=True, return_inverse=True)
    order = np.argsort(first_corner)
    new_index = np.empty(len(order), dtype=np.int32)
    new_index[order] = np.arange(len(order), dtype=np.int32)

    vertices = corner_vertices[first_corner[order]]
    faces = np.empty(len(triangle_loops), dtype=[("count", "u1"), ("indices", "<i4", (3,))])
    faces["count"] = 3
    faces["indices"] = new_index[unique_index.ravel()].reshape(-1, 3)

    uv_header = "property float s\nproperty float t\n" if uvs is not None else ""
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment Created by io_scene_render\n"
        f"element vertex {len(vertices)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        f"{uv_header}"
        f"element face {len(faces)}\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
    )
    with open(filepath, "wb") as out:
        out.write(header.encode("ascii"))
        vertices.tofile(out)
        faces.tofile(out)

def export_mesh_parts(parent, scene, depsgraph, object, nb_parts, folder, relative_folder, stem):
    """Write one PLY per material slot of the object.

    Returns the relative path of each part (None when no triangle uses the slot).
    """
    names = [f"{stem}_mat{i}.ply" for i in range(nb_parts)]
    todo = []
    results = [None] * nb_parts
    for i, name in enumerate(names):
        if os.path.exists(folder + name) and not scene.reexport_geometry:
            parent.report({'INFO'}, f"Skipping existing file: {folder + name}")
            results[i] = relative_folder + name
        else:
            todo.append(i)
    if len(todo) == 0:
        return results

    eval_obj = object.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        triangle_loops, triangle_parts, positions, normals, uvs = read_mesh_triangles(mesh, nb_parts)
        for i in todo:
            part_loops = triangle_loops[triangle_parts == i]
            if len(part_loops) == 0:
                continue
            parent.report({'INFO'}, f"Exporting file: {folder + names[i]} - Nb Tri: {len(part_loops)}")
            write_ply(folder + names[i], part_loops, positions, normals, uvs)
            results[i] = relative_folder + names[i]
    finally:
        eval_obj.to_mesh_clear()
    return results

def can_share_mesh(object):
    """Objects can share a file only when their evaluated geometry is the one of the mesh data."""
    return len(object.modifiers) == 0 and not object.show_only_shape_key

def unique_file_stem(stem, key, used_stems):
    """Make a mesh name usable as a file name, without clash with another mesh."""
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem)
    candidate = stem
    suffix = 1
    while used_stems.setdefault(candidate, key) != key:
        candidate = f"{stem}_{suffix}"
        suffix += 1
    return candidate

def export_objects(parent, filepath, scene, frameNumber):
    materials = [
        {"type" : "diffuse", "name" : "DEFAULT", "albedo" : [0.8, 0.8, 0.8]}
    ]
    shapes = []

    # The edits of a mesh in edit mode are only visible once back to object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # Create ouput directory
    relative_folder = 'meshes/' + frameNumber + '/'
    meshFolderPath = bpy.path.abspath(filepath + '/' + relative_folder)
    if not os.path.exists(meshFolderPath):
        parent.report({"INFO"},f'Meshes directory did not exist, creating: {meshFolderPath}')
        os.makedirs(meshFolderPath)

    # Files already written for this frame: objects sharing a mesh reuse them.
    # The renderers still load one copy per object (instancing is not supported).
    exported_parts = {}
    used_stems = {}


    # Compute the objects to export
    objects = []
    total = 0
    for object in scene.objects:
        if object.hide_render:
            parent.report({'INFO'}, f"Skipping hidden object: {object.name}")
            continue
        if object is not None and object.type == 'MESH':
            objects.append(object)
            total += 1
    
    # Get the window manager
    wm = bpy.context.window_manager
    wm.progress_begin(0, total)
        
    
    for (j, object) in enumerate(objects):
        # Export the object
        parent.report({'INFO'}, f"Exporting Object: {object.name}")
        wm.progress_update(j)

        # Export the geometry, once per mesh when the objects can share it
        nb_parts = max(len(object.material_slots), 1)
        if can_share_mesh(object):
            key = (object.data.as_pointer(), nb_parts)
            stem = object.data.name if object.data.users > 1 else object.name
        else:
            key = (object.as_pointer(), nb_parts)
            stem = object.name
        if key not in exported_parts:
            stem = unique_file_stem(stem, key, used_stems)
            exported_parts[key] = export_mesh_parts(parent, scene, depsgraph, object, nb_parts, meshFolderPath, relative_folder, stem)
        else:
            parent.report({'INFO'}, f"Reusing the files of mesh: {object.data.name}")

        for i in range(nb_parts):
            # Export the material if needed
            material = object.material_slots[i].material if len(object.material_slots) != 0 else None
            if len(object.material_slots) != 0 and material is None:
                parent.report({'WARNING'}, f"Empty material slot on object: {object.name}, using the default material")
                parent.error_or_warning = True
            if material is not None and material.name not in exportedMaterials:
                materials += export_material(parent, scene, material, filepath)
                exportedMaterials.append(material.name)

            # No triangle uses this material slot
            if exported_parts[key][i] is None:
                continue

            # Create entry
            # TODO: Manage participating media
            #exportObject_medium(scene_file, object.material_slots[0].material)
            shape_data = {}
            shape_data["type"] = "mesh"
            shape_data["filename"] = exported_parts[key][i]
            if material is not None:
                shape_data["material"] = material.name
            else:
                # Use the default material
                shape_data["material"] = "DEFAULT"

            matrix =  object.matrix_world # transposed()
            shape_data["transform"] = {
                "matrix" : [
                    matrix[0][0],matrix[0][1],matrix[0][2],matrix[0][3],
                    matrix[1][0],matrix[1][1],matrix[1][2],matrix[1][3],
                    matrix[2][0],matrix[2][1],matrix[2][2],matrix[2][3],
                    matrix[3][0],matrix[3][1],matrix[3][2],matrix[3][3]
                ]
            }                
            shapes += [shape_data]
    wm.progress_end()

    return (shapes, materials)
            

def export_integrator(parent, scene):
    int_data = {}
    if scene.integrators == 'path':
        int_data["type"] = "path"
        int_data["max_depth"] = scene.path_integrator_max_depth
    elif scene.integrators == 'normal':
        int_data["type"] = "normal"
    elif scene.integrators == "ao":
        int_data["type"] = "ao"
    else: 
        parent.report({'WARNING'}, " Wrong type of integrator")
        parent.error_or_warning = True
        int_data["type"] = "path" # Default
    return int_data

def export_background(parent, scene, filepath):
    # No world: black background
    if scene.world is None or scene.world.node_tree is None:
        return [0.0, 0.0, 0.0]

    # Fetch world
    outputNode = None
    for n in scene.world.node_tree.nodes:
        if n.type == 'OUTPUT_WORLD':
            outputNode = n
            break

    # No connection
    if outputNode is None or len(outputNode.inputs[0].links) == 0:
        return 0.0

    # Get the node
    node = outputNode.inputs[0].links[0].from_node
    if node.bl_idname == "ShaderNodeBackground":
        if scene.envmap:
            return texture_or_value(parent, node.inputs[0], filepath)
        else: 
            return only_value(parent, node.inputs[0])
    else:
        parent.report({'WARNING'}, f"Unsupported background node: {node.bl_idname}")
        parent.error_or_warning = True
        return [0.0, 0.0, 0.0]

def export_renderer(parent, filepath, scene , frameNumber):
    if filepath == "":
        filepath = os.path.dirname(bpy.data.filepath)
        if filepath == "":
            parent.report({'ERROR'}, "No output directory, and the blend file is not saved: aborting")
            parent.error_or_warning = True
            parent.fatal_error = True
            return
        parent.report({'WARNING'}, f"No output directory, using default: {filepath}")
    else:
        parent.report({'INFO'}, f"Exporting to: {filepath}")

    # Create output directory
    out = os.path.join(filepath, "test" + frameNumber +".json")
    if not os.path.exists(filepath):
        parent.report({'INFO'}, f'Output directory did not exist, creating: {filepath}')
        os.makedirs(filepath)

    # Create texture directory
    if not os.path.exists(filepath + "/textures"):
        parent.report({'INFO'}, f'Texture directory did not exist, creating: {filepath + "/textures"}')
        os.makedirs(filepath + "/textures")
    
    # Unpack all the local ressources
    # bpy.ops.file.unpack_all(method='USE_LOCAL')

    # Clear lsit of cached texture and materials
    exportedMaterials.clear()

    data_all ={}

    data_all["background"] = export_background(parent, scene, filepath)
    data_all["integrator"] = export_integrator(parent, scene)
    camera_and_sampler = export_camera(parent, scene)
    if camera_and_sampler is None:
        return
    (camera, sampler) = camera_and_sampler
    data_all["camera"] = camera
    data_all["sampler"] = sampler
    (shapes, materials) = export_objects(parent, filepath, scene, frameNumber)
    data_all["materials"] = materials
    data_all["shapes"] = shapes

    with open(out, 'w') as scene_file:
        scene_file.write(json.dumps(data_all, indent=4))
