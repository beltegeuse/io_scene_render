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

def export_camera(data_all, scene):
    print("Fetching camera..")
    cam_ob = bpy.context.scene.camera
    if cam_ob is None:
        print("no scene camera,aborting")
        self.report({'ERROR'}, "No camera in scene, aborting")
    elif cam_ob.type == 'CAMERA':
        print("regular scene cam")
        print("render res: ", scene.render.resolution_x , " x ", scene.render.resolution_y)
        print("Exporting camera: ", cam_ob.name)

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
        camera_dict["vfov"] = fov
        
        if scene.dofLookAt is not None:
            camera_dict["fdist"] = measure(cam_ob.matrix_world.translation, scene.dofLookAt.matrix_world.translation)
            camera_dict["aperture"] = scene.lensradius
        else:
            camera_dict["fdist"] = 1.0


        #Write out the sampler for the image.
        data_all["sampler"] = {
            "type" : "independent",
            "samples" : scene.spp
        }

        camera_dict["transform"] = {
            "from" : [from_point.x, from_point.y, from_point.z],
            "at" : [at_point.x, at_point.y, at_point.z],
            "up" : [up_point[0],up_point[1],up_point[2]]
        }

        data_all["camera"] = camera_dict


def texture_or_value (inputSlot, scene):
    """Return BSDF information"""
    links = inputSlot.links
    print('Number of links: ')
    print(len(links))
    for x in inputSlot.links:
        print("Checking input named: " + inputSlot.name)
        fromFile = bpy.path.abspath(x.from_node.image.filepath)
        head, tail = os.path.split(fromFile)

        print("Has a image named:" + tail)
        print("at path: " + bpy.path.abspath(x.from_node.image.filepath))
        print("going to type node:" + x.from_node.type)
        
        toFile = bpy.path.abspath(scene.exportpath + 'textures/' + tail)
        print("from file:")
        print(os.path.realpath(fromFile))
        print("to file:")
        print(os.path.realpath(toFile))
        if os.path.realpath(fromFile) != os.path.realpath(toFile):
            shutil.copyfile(os.path.realpath(fromFile), os.path.realpath(toFile))
        else:
            print("Texture source, and destination are the same, skipping copying.")
        
        return "textures/"+x.from_node.image.name
    # TODO: Pas de alpha
    return [inputSlot.default_value[0], inputSlot.default_value[1], inputSlot.default_value[2]]

def getTextureInSlotName(textureSlotParam):
    srcfile = textureSlotParam
    head, tail = os.path.split(srcfile)
    print("File name is :")
    print(tail)

    return tail

def export_material_node(mat, materialName, scene):
    print("export_material_node : " + mat.name)
    mat_data = {}
    if mat.bl_idname == 'ShaderNodeBsdfDiffuse':
        mat_data["type"] = "diffuse"
        mat_data["albedo"] = texture_or_value(mat.inputs[0], scene)
    elif mat.bl_idname == "ShaderNodeEmission":
        mat_data["type"] = "diffuse_light"
        mat_data["radiance"] = texture_or_value(mat.inputs[0], scene)
    else:
        print(f"WARN: Wrong material: {materialName} | type: {mat.bl_idname}")
        mat_data["type"] = "diffuse"

    # Give name 
    mat_data["name"] = materialName
    return mat_data

def export_material(data_all, material, scene):
    if material is None:
        print("no material on object")

    print ('Exporting material named: ', material.name)
    currentMaterial = None
    material.use_nodes = True
    if material and material.use_nodes: #if it is using nodes
        print('Exporting materal named: ', material.name)
        #Find the surface output node, then export the connected material
        for node in material.node_tree.nodes:
            if node.name == 'Material Output':
                for input in node.inputs:
                    for node_links in input.links:
                        currentMaterial =  node_links.from_node
                        data_all["materials"].append(export_material_node(currentMaterial, material.name, scene))

def createDefaultExportDirectories(scene):
    texturePath = bpy.path.abspath(scene.exportpath + 'textures')
    print("Exporting textures to: ")
    print(texturePath)

    if not os.path.exists(texturePath):
        print('Texture directory did not exist, creating: ')
        print(texturePath)
        os.makedirs(texturePath)

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

def export_gometry_as_obj(data_all, scene, frameNumber):
    objects = scene.objects
    for object in objects:
        print("exporting:")
        print(object.name)

        if object is not None and object.type != 'CAMERA' and object.type == 'MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            print('exporting object: ' + object.name)
            bpy.context.view_layer.update()
            object.data.update()
            dg = bpy.context.evaluated_depsgraph_get()
            eval_obj = object.evaluated_get(dg)
            mesh = eval_obj.to_mesh()
            if not mesh.loop_triangles and mesh.polygons:
                print("loop triangles...")
                mesh.calc_loop_triangles()

            # Compute normals
            mesh.calc_normals_split()

            for i in range(max(len(object.material_slots), 1)):
                if len(object.material_slots) != 0:
                    material = object.material_slots[i].material
                    if material.name not in exportedMaterials:
                        export_material(data_all, material, scene)
                        exportedMaterials.append(material.name)
                else:
                    pass # TODO: Not material
                
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
                print("Nb Tri: ", len(indices) // 3) 
            
                # Create ouput directory
                objFolderPath =  bpy.path.abspath(scene.exportpath + 'meshes/' + frameNumber + '/')
                if not os.path.exists(objFolderPath):
                    print('Meshes directory did not exist, creating: ')
                    print(objFolderPath)
                    os.makedirs(objFolderPath)

                # Compute the path variables
                objFilePath = objFolderPath + object.name + f'_mat{i}.obj' 
                objFilePathRel = 'meshes/' + frameNumber + '/' + object.name + f'_mat{i}.obj'

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
                
                matrix =  object.matrix_world # transposed()
                shape_data["transform"] = {
                    "matrix" : [
                        matrix[0][0],matrix[0][1],matrix[0][2],matrix[0][3],
                        matrix[1][0],matrix[1][1],matrix[1][2],matrix[1][3],
                        matrix[2][0],matrix[2][1],matrix[2][2],matrix[2][3],
                        matrix[3][0],matrix[3][1],matrix[3][2],matrix[3][3]
                    ]
                }                
                data_all["shapes"].append(shape_data)


    return ''
            

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

def export_renderer(filepath, scene , frameNumber):
    out = os.path.join(filepath, "test" + frameNumber +".json")
    if not os.path.exists(filepath):
        print('Output directory did not exist, creating: ')
        print(filepath)
        os.makedirs(filepath)
    
    # Clear lsit of cached texture and materials
    exportedMaterials.clear()

    with open(out, 'w') as scene_file:
        data_all ={}
        # data_all["background"] = [1, 1, 1] # Main configuration?
        data_all["materials"]=[]
        data_all["shapes"]=[]

        createDefaultExportDirectories(scene)
        data_all["integrator"] = export_integrator(scene)
        export_camera(data_all, scene)
        export_gometry_as_obj(data_all,scene, frameNumber)
        
        exported_json_string = json.dumps(data_all, indent=4)
        scene_file.write(exported_json_string)
        scene_file.close()
        
