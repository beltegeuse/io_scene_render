import bpy
import os
from . import render_exporter

class ExportRendererScene(bpy.types.Operator):
    bl_idname = 'scene.export'
    bl_label = 'Export Scene'
    bl_options = {"REGISTER", "UNDO"}
    COMPAT_ENGINES = {'Renderer_Renderer'}
    
    # Error handling
    fatal_error = False
    error_or_warning = False
    
    def execute(self, context):
        # Get the scene and abs path (if provided)
        currentScene = bpy.context.scene
        exportPath = bpy.path.abspath(currentScene.exportpath)
        
        # Reset error handling
        self.error_or_warning = False
        self.fatal_error = False
        
        for frameNumber in range(currentScene.batch_frame_start, currentScene.batch_frame_end +1):
            currentScene.frame_set(frameNumber)
            print("Exporting frame: %s" % (frameNumber))
            render_exporter.export_renderer(self, exportPath, currentScene, '{0:05d}'.format(frameNumber))
            
        # Check if there was an error during export
        if self.error_or_warning:
            if self.fatal_error:
                self.report({'ERROR'}, "Export failed (please check log) - likely a fatal error that will prevent to use the scene.")
            else:
                self.report({'WARNING'}, "Export generated warnings (please check log).")
        else:
            self.report({'INFO'}, "Export complete.")
        return {"FINISHED"}

class RendererRenderSettingsPanel(bpy.types.Panel):
    """Creates a MTI Renderer settings panel in the render context of the properties editor"""
    bl_label = "MTI Render settings"
    bl_idname = "SCENE_PT_layout"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    COMPAT_ENGINES = {'Renderer_Renderer'}

    @classmethod
    def poll(cls, context):
        engine = context.scene.render.engine
        if engine != 'Renderer_Renderer':
            return False
        else:
            return True

    def draw(self, context):
        engine = context.scene.render.engine
        if engine != 'Renderer_Renderer':
            bpy.utils.unregister_class(RendererRenderSettingsPanel)

        layout = self.layout

        scene = context.scene

        layout.label(text="Output folder path")
        row = layout.row()
        
        row.prop(scene, "exportpath")

        layout.label(text="Frame settings:")
        row = layout.row()
        row.prop(scene, "batch_frame_start")
        row.prop(scene, "batch_frame_end")

        layout.label(text="Resolution:")
        row = layout.row()
        row.prop(scene, "resolution_x")
        row.prop(scene, "resolution_y")

        row = layout.row()
        row.prop(scene,"spp")

        layout.label(text="Depth of field:")
        row = layout.row()
        row.prop(scene,"dofLookAt")
        row = layout.row()
        row.prop(scene, "lensradius")

        layout.label(text="Integrator settings:")
        row = layout.row()

        # row.prop(scene,"integrators")
        # if scene.integrators == 'path':
        #     row = layout.row()
        #     row.prop(scene,"path_integrator_max_depth")
        # if scene.integrators == 'direct':
        #     pass
        # if scene.integrators == 'normal':
        #     pass
        
        layout.label(text="Export:")
        row = layout.row()
        layout.prop(scene, "export_normal_map")
        row = layout.row()
        layout.prop(scene, "reexport_geometry")
        row = layout.row()
        layout.prop(scene, "improved_principled")
        row = layout.row()
        layout.prop(scene, "envmap")
        
        row = layout.row()
        layout.operator("scene.export", icon='MESH_CUBE', text="Export scene")

def register():
    
    bpy.types.Scene.exportpath = bpy.props.StringProperty(
        name="",
        description="Export folder",
        default="",
        maxlen=1024,
        subtype='DIR_PATH')

    bpy.types.Scene.spp = bpy.props.IntProperty(name = "Samples per pixel", description = "Set spp", default = 100, min = 1, max = 9999)
    bpy.types.Scene.resolution_x = bpy.props.IntProperty(name = "X", description = "Resolution x", default = 1366, min = 1, max = 9999)
    bpy.types.Scene.resolution_y = bpy.props.IntProperty(name = "Y", description = "Resolution y", default = 768, min = 1, max = 9999)
    bpy.types.Scene.dofLookAt = bpy.props.PointerProperty(name="Target", type=bpy.types.Object)
    bpy.types.Scene.lensradius = bpy.props.FloatProperty(name = "Lens radius", description = "Lens radius", default = 0, min = 0.001, max = 9999)
    bpy.types.Scene.batch_frame_start = bpy.props.IntProperty(name = "Frame start", description = "Frame start", default = 1, min = 1, max = 9999999)
    bpy.types.Scene.batch_frame_end = bpy.props.IntProperty(name = "Frame end", description = "Frame end", default = 1, min = 1, max = 9999999)

    bpy.types.Scene.export_normal_map = bpy.props.BoolProperty(name = "Export normal map", description = "Export normal map", default = False)
    bpy.types.Scene.reexport_geometry = bpy.props.BoolProperty(name = "Reexport geometry", description = "Reexport geometry", default = True)
    bpy.types.Scene.improved_principled = bpy.props.BoolProperty(name = "Improved Principled", description = "Improved Principled export", default = False)
    bpy.types.Scene.envmap = bpy.props.BoolProperty(name = "Export envmap", description = "Export envmap", default = False)
    
    integrators = [("path", "path", "", 1),("normal", "normal", "", 2),("ao", "ao", "", 3)]
    bpy.types.Scene.integrators = bpy.props.EnumProperty(name = "Name", items=integrators , default="path")
    
    

    # Specific settings
    bpy.types.Scene.path_integrator_max_depth = bpy.props.IntProperty(name = "Max depth", description = "Specifies the longest path depth in the generated output image (where -1 corresponds to infty). A value of 1 will only render directly visible light sources. 2 will lead to single-bounce (direct-only) illumination, and so on.", default = 16, min = -1, max = 9999)
    