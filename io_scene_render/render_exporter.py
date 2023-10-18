import bpy
import bmesh
import os
import math
from math import *
import mathutils
from mathutils import Vector
import shutil
import json

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
for member in dir(properties_render):
    subclass = getattr(properties_render, member)
    try:
        subclass.COMPAT_ENGINES.add('Renderer_Renderer')
    except:
        pass

for member in dir(properties_material):
    subclass = getattr(properties_material, member)
    try:
        subclass.COMPAT_ENGINES.add('Renderer_Renderer')
    except:
        pass

bpy.utils.register_class(RendererRenderEngine)
exportedMaterials = list()

#Camera code:
#https://blender.stackexchange.com/questions/16472/how-can-i-get-the-cameras-projection-matrix
def measure(first, second):
    locx = second[0] - first[0]
    locy = second[1] - first[1]
    locz = second[2] - first[2]

    distance = sqrt((locx)**2 + (locy)**2 + (locz)**2)
    return distance

def export_camera(scene):
    print("INFO: Fetching camera..")
    cam_ob = bpy.context.scene.camera
    if cam_ob is None:
        print("ERROR: no scene camera,aborting")
        return {}
    elif cam_ob.type == 'CAMERA':
        print(f"INFO: Exporting camera: {cam_ob.name} [{scene.render.resolution_x}x{scene.render.resolution_y}]")

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
        fov = bpy.data.cameras[0].angle * 180 / math.pi
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

def texture_copy(node, filepath):
    fromFile = bpy.path.abspath(node.image.filepath)
    head, tail = os.path.split(fromFile)
    
    toFile = bpy.path.abspath(filepath + '/textures/' + tail)
    print(f"INFO: Copying texture: {fromFile} to {toFile}")
    if os.path.realpath(fromFile) != os.path.realpath(toFile):
        if os.path.exists(toFile):
            print(f"WARN: Texture already exist: {toFile}. Do not copy")
        else:
            shutil.copyfile(os.path.realpath(fromFile), os.path.realpath(toFile))

def texture_or_value (inputSlot, filepath, scale=1.0, is_normal_map = False):
    """Return BSDF information"""
    if(len(inputSlot.links) == 0):
        # TODO: Pas de alpha
        # print("No link, use value directly")
        return {
            "type" : "constant",
            "value" : [inputSlot.default_value[0] * scale, 
                       inputSlot.default_value[1] * scale, 
                       inputSlot.default_value[2] * scale]
        }
    
    # print(f"Number links: {len(inputSlot.links)}")
    node = inputSlot.links[0].from_node # Take always the first link

    # Check if normal map, and get the node
    if node.bl_idname == "ShaderNodeNormalMap":
        print(f"WARN: Detect normal map, Strength is ignored: {node.inputs['Strength'].default_value}")
        node = node.inputs["Color"].links[0].from_node
        

    print(f"INFO: Texture type: {node.bl_idname}")
    if node.bl_idname == "ShaderNodeTexChecker":
        print("INFO: Detect checkerboard texture")
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
        texture_copy(node, filepath)
        return {
            "type" : "texture",
            "filename" : "textures/"+node.image.name,
        }
    elif node.bl_idname == "ShaderNodeTexImage":
        filename = os.path.split(node.image.filepath.replace("\\","//"))[1]
        print(f"INFO: Detect Texture image: {node.image.name} | {filename}") 
        texture_copy(node, filepath)
        if len(node.inputs[0].links) > 0:
            print(f"INFO: Number links For Texture mapping: {len(node.inputs[0].links)}")

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
        print(f"WARN: Unsupported node export: {node.bl_idname}")
        if is_normal_map:
            return {
                "type" : "constant",
                "value" : [0, 0, 1]
            }
        else:
            return {
                "type" : "constant",
                "value" : [inputSlot.default_value[0] * scale, 
                        inputSlot.default_value[1] * scale, 
                        inputSlot.default_value[2] * scale]
            }
            

def export_material_node(mat, materialName, filepath):
    print("INFO: Exporting material node : " + mat.name)
    mat_data = {}
    if mat.bl_idname == 'ShaderNodeBsdfDiffuse':
        mat_data["type"] = "diffuse"
        mat_data["albedo"] = texture_or_value(mat.inputs[0], filepath)
    elif mat.bl_idname == "ShaderNodeEmission":
        mat_data["type"] = "diffuse_light"
        scale = mat.inputs[1].default_value
        mat_data["radiance"] = texture_or_value(mat.inputs[0], filepath, scale)
    elif mat.bl_idname == "ShaderNodeBsdfGlass":
        mat_data["type"] = "dielectric"
        mat_data["ks"] = texture_or_value(mat.inputs[0], filepath) # Color
        mat_data["roughness"] = mat.inputs[1].default_value     # Roughness
        mat_data["eta_int"] = mat.inputs[2].default_value       # IOR
        # TODO: Export IOR (texture - 1d)
    elif mat.bl_idname == "ShaderNodeBsdfGlossy":
        mat_data["type"] = "metal"
        mat_data["ks"] = texture_or_value(mat.inputs[0], filepath)
        mat_data["roughness"] = mat.inputs[1].default_value
    elif mat.bl_idname == "ShaderNodeBsdfPrincipled":
        print("WARN: Principled shader not fully supported")
        # Export as diffuse
        local_material = {}
        local_material["type"] = "diffuse"
        local_material["albedo"] = texture_or_value(mat.inputs[0], filepath)
        # TODO: Export other parameters
        if texture_might_exist(mat.inputs["Normal"]):
            # Normal map added if found
            mat_data["type"] = "normal_map"
            mat_data["normal_map"] = texture_or_value(mat.inputs["Normal"], filepath, is_normal_map = True)
            mat_data["material"] = local_material
        else:
            mat_data = local_material
            
    else:
        print(f"WARN: Wrong material: {materialName} | type: {mat.bl_idname}")
        mat_data["type"] = "diffuse"

    # Give name 
    mat_data["name"] = materialName
    return mat_data

def export_material(material, filepath):
    if material is None:
        print("WARN: no material on object")
    mats = []
    print (f'INFO: Exporting material named: {material.name}')
    currentMaterial = None
    material.use_nodes = True
    if material and material.use_nodes: 
        for node in material.node_tree.nodes:
            if node.type == "OUTPUT_MATERIAL":
                for input in node.inputs:
                    for node_links in input.links:
                        currentMaterial =  node_links.from_node
                        mats += [export_material_node(currentMaterial, material.name, filepath)]
    return mats

def write_obj(file, mesh, indices, normals, i):
    # Pack U,V
    uvs = []
    for uv_layer in mesh.uv_layers:
        for tri in mesh.loop_triangles:
            if tri.material_index == i:
                for loop_index in tri.loops:
                    uvs.append((
                        uv_layer.data[loop_index].uv[0],
                        uv_layer.data[loop_index].uv[1]
                    ))

    # write obj
    out = open(file, 'w')

    # write vertices positions
    for id_vertex in indices:
        out.write('v {:.6f} {:.6f} {:.6f}\n'.format( 
            mesh.vertices[id_vertex].co.x, 
            mesh.vertices[id_vertex].co.y, 
            mesh.vertices[id_vertex].co.z)
        )
    
    for n in normals:
        out.write('vn {:.6f} {:.6f} {:.6f}\n'.format(n[0], n[1], n[2]))

    if len(uvs) != 0:
        for id in range(len(indices)):
            out.write('vt {:.6f} {:.6f}\n'.format(uvs[id][0],  uvs[id][1]))

    # write f: ver ind/ uv ind
    for i in range(0, len(indices), 3):
        if len(uvs) != 0:
            out.write(f'f {i+1}/{i+1}/{i+1} {i+2}/{i+2}/{i+2} {i+3}/{i+3}/{i+3}\n')
        else:
           out.write(f'f {i+1}//{i+1} {i+2}//{i+2} {i+3}//{i+3}\n')

def export_objects(filepath, scene, frameNumber):
    materials = [
        {"type" : "diffuse", "name" : "DEFAULT", "albedo" : [0.8, 0.8, 0.8]}
    ]
    shapes = []

    objects = scene.objects
    for object in objects:
        print(f"INFO: Exporting Object: {object.name}")

        if object is not None and object.type != 'CAMERA' and object.type == 'MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.view_layer.update()
            object.data.update()
            dg = bpy.context.evaluated_depsgraph_get()
            eval_obj = object.evaluated_get(dg)
            mesh = eval_obj.to_mesh()
            if not mesh.loop_triangles and mesh.polygons:
                print("WARN: loop triangles...")
                mesh.calc_loop_triangles()

            # Compute normals
            mesh.calc_normals_split()

            for i in range(max(len(object.material_slots), 1)):
                # Export the mesh
                indices = []
                normals = []
                for loop_tri in mesh.loop_triangles:
                    polygon = mesh.polygons[loop_tri.polygon_index]
                    if polygon.material_index == i:
                        for loop_index in loop_tri.loops:
                            vertex_index = mesh.loops[loop_index].vertex_index
                            indices.append(vertex_index)
                            normals.append(mesh.loops[loop_index].normal)
                print(f"INFO: Nb Tri: {len(indices) // 3}") 
                if(len(indices) == 0):
                    continue 
                
                # Export the material if needed
                if len(object.material_slots) != 0:
                    material = object.material_slots[i].material
                    if material.name not in exportedMaterials:
                        materials += export_material(material, filepath)
                        exportedMaterials.append(material.name)
                    
            
                # Create ouput directory
                objFolderPath =  bpy.path.abspath(filepath + './meshes/' + frameNumber + '/')
                if not os.path.exists(objFolderPath):
                    print(f'Meshes directory did not exist, creating: {objFolderPath}')
                    os.makedirs(objFolderPath)

                # Compute the path variables
                objName = object.name + f'_mat{i}.obj' 
                objName = objName.replace(":","_")
                objFilePath = objFolderPath + objName
                objFilePathRel = 'meshes/' + frameNumber + '/' + objName

                # Export obj manually
                write_obj(objFilePath, mesh, indices, normals, i)

                # Create entry
                # TODO: Manage participating media
                #exportObject_medium(scene_file, object.material_slots[0].material)
                shape_data = {}
                shape_data["type"] = "mesh"
                shape_data["filename"] = objFilePathRel
                if len(object.material_slots) != 0:
                    shape_data["material"] = object.material_slots[i].material.name
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

    return (shapes, materials)
            

def export_integrator(scene):
    int_data = {}
    if scene.integrators == 'path':
        int_data["type"] = "path"
        int_data["max_depth"] = scene.path_integrator_max_depth
    elif scene.integrators == 'normal':
        int_data["type"] = "normal"
    elif scene.integrators == "ao":
        int_data["type"] = "ao"
    else: 
        print("WARN: Wrong type of integrator")
        int_data["type"] = "path" # Default
    return int_data

def export_background(scene, filepath):
    # Fetch world
    outputNode = None
    for n in scene.world.node_tree.nodes:
        if n.type == 'OUTPUT_WORLD':
            outputNode = n
            break
    
    # No connection
    if len(outputNode.inputs[0].links) == 0:
        return 0.0
    
    # Get the node
    node = outputNode.inputs[0].links[0].from_node
    if node.bl_idname == "ShaderNodeBackground":
        return texture_or_value(node.inputs[0], filepath)
    else:
        print(f"WARN: Unsupported background node: {node.bl_idname}")
        return [0.0, 0.0, 0.0]

def export_renderer(filepath, scene , frameNumber):
    if filepath == "":
        filepath = os.path.dirname(bpy.data.filepath)
        print(f"WARN: No output directory, using default: {filepath}")
    else:
        print(f"INFO: Exporting to: {filepath}")

    # Create output directory
    out = os.path.join(filepath, "test" + frameNumber +".json")
    if not os.path.exists(filepath):
        print(f'INFO: Output directory did not exist, creating: {filepath}')
        os.makedirs(filepath)

    # Create texture directory
    if not os.path.exists(filepath + "/textures"):
        print(f'INFO: Texture directory did not exist, creating: {filepath + "/textures"}')
        os.makedirs(filepath + "/textures")
    
    # Unpack all the local ressources
    # bpy.ops.file.unpack_all(method='USE_LOCAL')

    # Clear lsit of cached texture and materials
    exportedMaterials.clear()

    with open(out, 'w') as scene_file:
        data_all ={}
        
        data_all["background"] = export_background(scene, filepath)
        data_all["integrator"] = export_integrator(scene)
        (camera, sampler) = export_camera(scene)
        data_all["camera"] = camera
        data_all["sampler"] = sampler
        (shapes, materials) = export_objects(filepath, scene, frameNumber)
        data_all["shapes"] = shapes
        data_all["materials"] = materials

        exported_json_string = json.dumps(data_all, indent=4)
        scene_file.write(exported_json_string)
        scene_file.close()
        
