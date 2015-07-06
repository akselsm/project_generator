# Copyright 2014-2015 0xc0170
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import yaml
import shutil
import logging

from collections import defaultdict
from .tool import build, export, flash, ToolsSupported
from .util import flatten, merge_recursive

try:
    input = raw_input
except:
    pass

FILES_EXTENSIONS = {
    'include_paths': ['h', 'hpp', 'inc'],
    'source_files_s': ['s'],
    'source_files_c': ['c'],
    'source_files_cpp': ['cpp', 'cc'],
    'source_files_lib': ['lib', 'ar', 'a'],
    'source_files_obj': ['o', 'obj'],
    'linker_file': ['sct', 'ld', 'lin', 'icf'],
}


class ToolSpecificSettings:

    """represents the settings that are specific to targets"""

    def __init__(self):
        self.include_paths = []
        self.source_paths = []
        self.source_groups = {}
        self.macros = []
        self.misc = {}

        self.linker_file = None
        self.template = None

    def add_settings(self, data_dictionary, group_name):
        if 'sources' in data_dictionary:
            self._process_source_files(
                data_dictionary['sources'], group_name)

        if 'includes' in data_dictionary:
            self.include_paths.extend([x for x in data_dictionary['includes'] if x is not None])

        if 'macros' in data_dictionary:
            self.macros.extend([x for x in data_dictionary['macros'] if x is not None])

        if 'project_dir' in data_dictionary:
            # ??? project_dir defined in Project but not ToolSpecificSettings: unresolved attribute reference
            self.project_dir.update(data_dictionary['project_dir'])

        if 'linker_file' in data_dictionary:
            self.linker_file = data_dictionary['linker_file'][0]

        if 'misc' in data_dictionary:
            self.misc.update(data_dictionary['misc'])

        if 'template' in data_dictionary:
            self.template = data_dictionary['template']

    def source_of_type(self, filetype):
        """return a dictionary of groups and the sources of a specified type within them"""
        files = {}
        for group, group_contents in self.source_groups.items():
            files[group] = []
            if filetype in group_contents:
                files[group].extend(group_contents[filetype])

        return files

    def all_sources_of_type(self, filetype):
        """return a list of the sources of a specified type"""
        files = []

        for group, group_contents in self.source_groups.items():
            if filetype in group_contents:
                files.extend(group_contents[filetype])

        return files

    def _process_source_files(self, files, group_name):
        extensions = ['cpp', 'c', 's', 'obj', 'lib']
        mappings = defaultdict(lambda: None)

        mappings['o'] = 'obj'

        mappings['a'] = 'lib'
        mappings['ar'] = 'lib'
        mappings['cc'] = 'cpp'

        if group_name not in self.source_groups:
            self.source_groups[group_name] = {}

        for source_file in files:
            extension = source_file.split('.')[-1]
            extension = mappings[extension] or extension

            if extension not in extensions:
                continue

            if extension not in self.source_groups[group_name]:
                self.source_groups[group_name][extension] = []

            self.source_groups[group_name][extension].append(source_file)

            if os.path.dirname(source_file) not in self.source_paths:
                self.source_paths.append(os.path.dirname(source_file))


class ProjectWorkspace:
    """represents a workspace (multiple projects) """

    def __init__(self, proj_name, projects, pgen_workspace, singular = False):
        self.name = proj_name
        self.projects = projects
        self.pgen_workspace = pgen_workspace # TODO: FIX me please
        self.generated_files = {}
        self.singular = singular

    def export(self, tool, copy):
        """ Exports workspace """
        tools = []
        if not tool:
            tools = self.tools_supported
        else:
            tools = [tool]

        for export_tool in tools:
            exporter = ToolsSupported().get_value(export_tool, 'exporter')
            workspace_dic = {
                'projects': [],
                'settings': {},
            }
            for project in self.projects:
                workspace_dic['projects'].append(project.generate_dic(export_tool, copy))
            logging.debug("Project workspace dict: %s" % workspace_dic)
            generated_files = export(exporter, workspace_dic, export_tool, self.pgen_workspace.settings)

            self.generated_files[export_tool] = generated_files

class Project:

    """represents a project, which can be formed of many yaml files"""

    def __init__(self, name, project_files, pgen_workspace):
        """initialise a project with a yaml file"""

        self.workspace = pgen_workspace

        self.name = name

        self.include_paths = []
        self.source_paths = []
        self.source_groups = {}
        self.macros = []
        self.project_dir = {
            'name': '',
            'path': '',
        }
        self.build_dir = 'build'
        self.output_dir = {
            'path': '',
            'rel_path': '',
            'rel_count': '',
        }
        self.mcu = ''
        self.core = ''
        self.target = ''
        self.tools_supported = []

        self.output_types = {
            'executable': 'exe',
            'exe': 'exe',
            'library': 'lib',
            'lib': 'lib',
        }
        self.output_type = self.output_types['executable']

        self.debugger = 'cmsis-dap'

        self.linker_file = None
        self.tool_specific = defaultdict(ToolSpecificSettings)

        # self.project_path = {}
        # self.project_files = {}
        self.project_name = None
        self.tools = ToolsSupported()

        for project_file in project_files:
            try:
                f = open(project_file, 'rt')
                project_file_data = yaml.load(f)
                self.set_attributes(project_file_data)
            except IOError:
               raise IOError("The file %s referenced in main yaml doesn't exist."%project_file)

        if self.project_dir['path'] == '':
            self.project_dir['path'] = self.workspace.settings.generated_projects_dir_default

        if len(self.tools_supported) == 0:
            self.tools_supported = [self.workspace.settings.DEFAULT_TOOL]

    def set_attributes(self,project_file_data):
        if 'common' in project_file_data:
                if 'output' in project_file_data['common']:
                    if project_file_data['common']['output'][0] not in self.output_types:
                        raise RuntimeError("Invalid Output Type.")

                    self.output_type = self.output_types[project_file_data['common']['output'][0]]

                if 'includes' in project_file_data['common']:
                    self.include_paths.extend(
                        [os.path.normpath(x) for x in project_file_data['common']['includes'] if x is not None])

                if 'sources' in project_file_data['common']:
                    if type(project_file_data['common']['sources']) == type(dict()):
                        # ??? local variables source_paths and group_names not used
                        group_names = project_file_data['common']['sources'].keys()
                        source_paths = [self._process_source_files(project_file_data['common']['sources'][group_name],
                                                                   group_name) for group_name in group_names]
                    else:
                        if 'group_name' in project_file_data['common']:
                            group_name = project_file_data['common']['group_name'][0]
                        else:
                            group_name = 'default'
                        self._process_source_files(project_file_data['common']['sources'], group_name)
                    for source_path in self.source_paths:
                        if os.path.normpath(source_path) not in self.include_paths:
                            self.include_paths.extend([source_path])

                if 'macros' in project_file_data['common']:
                    self.macros.extend(
                        [x for x in project_file_data['common']['macros'] if x is not None])

                if 'project_dir' in project_file_data['common']:
                    self.project_dir.update(
                        project_file_data['common']['project_dir'])

                if 'core' in project_file_data['common']:
                    self.core = project_file_data['common']['core'][0]

                if 'target' in project_file_data['common']:
                    self.target = project_file_data['common']['target'][0]

                if 'name' in project_file_data['common']:
                    self.name = project_file_data['common'][0]

                if 'mcu' in project_file_data['common']:
                    self.mcu = project_file_data['common']['mcu'][0]

                if 'build_dir' in project_file_data['common']:
                    self.build_dir = project_file_data['common']['build_dir'][0]

                if 'debugger' in project_file_data['common']:
                    self.debugger = project_file_data['common']['debugger'][0]

                if 'tools_supported' in project_file_data['common']:
                    self.tools_supported.extend(
                        [x for x in project_file_data['common']['tools_supported'] if x is not None])

        if 'tool_specific' in project_file_data:
            group_name = 'default'
            for tool_name, tool_settings in project_file_data['tool_specific'].items():
                self.tool_specific[tool_name].add_settings(tool_settings, group_name)

    def _process_source_files(self, files, group_name):
        source_paths = []
        extensions = ['cpp', 'c', 's', 'obj', 'lib']
        mappings = defaultdict(lambda: None)
        mappings['o'] = 'obj'
        mappings['a'] = 'lib'
        mappings['ar'] = 'lib'
        mappings['cc'] = 'cpp'
        if group_name not in self.source_groups:
            self.source_groups[group_name] = {}

        for source_file in files:
            if os.path.isdir(source_file):
                self.source_paths.append(os.path.normpath(source_file))
                self._process_source_files([os.path.join(os.path.normpath(source_file), f) for f in os.listdir(
                    source_file) if os.path.isfile(os.path.join(os.path.normpath(source_file), f))], group_name)

            extension = source_file.split('.')[-1]
            extension = mappings[extension] or extension

            if extension not in extensions:
                continue

            if extension not in self.source_groups[group_name]:
                self.source_groups[group_name][extension] = []

            self.source_groups[group_name][extension].append(os.path.normpath(source_file))

            if not os.path.dirname(source_file) in self.source_paths:
                self.source_paths.append(os.path.normpath(os.path.dirname(source_file)))
        return source_paths

    def clean(self, project_name, tool):
        if tool is None:
            tools = list(self.TOOLCHAINS)
        else:
            tools = [tool]

        for current_tool in tools:
            if self.workspace.settings.generated_projects_dir != self.workspace.settings.generated_projects_dir_default:
                # TODO: same as in exporters.py - create keyword parser
                path = self.workspace.settings.generated_projects_dir
                path = path.replace('$tool$', tool)
                path = path.replace('$project_name$', project_name)
                if self.target:
                    path = path.replace('$target$', self.target)
            else:
                 path = os.path.join(self.project_dir['path'], "%s_%s" % (current_tool, self.name))
            if os.path.isdir(path):
                logging.info("Cleaning directory %s" % path)

                shutil.rmtree(path)

    def build(self, tool):
        """build the project"""
        tools = []
        if not tool:
            tools = self.tools_supported
        else:
            tools = [tool]

        for build_tool in tools:
            builder = self.tools.get_value(build_tool, 'builder')
            proj_dic = self.generate_dict_for_tool(build_tool)
            if proj_dic['project_dir']['name'] and proj_dic['project_dir']['path']:
                project_files = [os.path.join(proj_dic['project_dir']['path'], proj_dic['project_dir']['name'])]
            else:
                project_files = [os.path.join(proj_dic['output_dir']['path'], proj_dic['name'])]
            build(builder, self.name, project_files, build_tool, self.workspace.settings)

    def flash(self, tool):
        """flash the project"""
        # flashing via various tools does not make much usefulness?
        if not tool:
            tool = self.workspace.settings.DEFAULT_TOOL

        flasher = self.tools.get_value(tool, 'flasher')
        proj_dic = self.generate_dict_for_tool(tool)
        if proj_dic['project_dir']['name'] and proj_dic['project_dir']['path']:
            project_files = [os.path.join(proj_dic['project_dir']['path'], proj_dic['project_dir']['name'])]
        else:
            project_files = [os.path.join(proj_dic['output_dir']['path'], proj_dic['name'])]
        flash(flasher, proj_dic, self.name, project_files, tool, self.workspace.settings)

    def generate_dic(self, tool, copy):
        """export the project"""
        proj_dic = self.generate_dict_for_tool(tool)
        proj_dic['copy_sources'] = False
        proj_dic['output_dir']['rel_path'] = ''

        if copy:
            self.copy_files(proj_dic, tool)
            # TODO: fixme
            proj_dic['copy_sources'] = True
        else:
            # Get number of how far we are from root, to set paths in the project
            # correctly
            count = 1
            pdir = proj_dic['output_dir']['path']
            while os.path.split(pdir)[0]:
                pdir = os.path.split(pdir)[0]
                count += 1
            rel_path_output = ''

            proj_dic['output_dir']['rel_count'] = count
            while count:
                rel_path_output = os.path.join('..', rel_path_output)
                count -= 1
            proj_dic['output_dir']['rel_path'] = rel_path_output

        return proj_dic

    def source_of_type(self, filetype):
        """return a dictionary of groups and the sources of a specified type within them"""
        files = {}
        for group, group_contents in self.source_groups.items():
            files[group] = []
            if filetype in group_contents:
                files[group].extend(group_contents[filetype])
        return files

    def all_sources_of_type(self, filetype):
        """return a list of the sources of a specified type"""
        files = []
        for group, group_contents in self.source_groups.items():
            if filetype in group_contents:
                files.extend(group_contents[filetype])
        return files

    def format_source_files(self, ext, tool_specific_settings, toolchain_specific_settings):
        return [merge_recursive(self.source_of_type(ext), {k: v for settings in
               [settings.source_of_type(ext) for settings in tool_specific_settings] for
               k, v in settings.items()},toolchain_specific_settings.source_of_type(ext))]

    def generate_dict_for_tool(self, tool):
        """for backwards compatibility"""
        toolchain_specific_settings =  self.tool_specific[self.tools.get_value(tool, 'toolchain')]
        tool_specific_settings = []
        toolnames = self.tools.get_value(tool, 'toolnames')
        for tool_spec in toolnames:
            if self.tools.get_value(tool, 'toolchain') != tool_spec:
                tool_specific_settings.append(self.tool_specific[tool_spec])

        d = {
            'name': self.name,
            'mcu': self.mcu,
            'core': self.core,
            'target': self.target,
            'output_type': self.output_type,
            'build_dir': self.build_dir,
            'tools_supported': self.tools_supported,
            'debugger': self.debugger,
            'output_dir': self.output_dir,
            'includes':
                self.include_paths + list(flatten([settings.include_paths for settings in tool_specific_settings])),
            'source_paths':
                self.source_paths + list(flatten([settings.source_paths for settings in tool_specific_settings])),

            'source_files':
                merge_recursive(self.source_groups,
                                {k: v for settings in tool_specific_settings for k, v in settings.source_groups.items()},
                                toolchain_specific_settings.source_groups),
            # for backwards compatibility
            'source_files_c': self.format_source_files('c',tool_specific_settings, toolchain_specific_settings),

            'source_files_cpp': self.format_source_files('cpp',tool_specific_settings, toolchain_specific_settings),

            'source_files_s':  self.format_source_files('s',tool_specific_settings, toolchain_specific_settings),

            'source_files_obj': merge_recursive(self.format_source_files('obj',tool_specific_settings, toolchain_specific_settings),
                                                self.format_source_files('o',tool_specific_settings, toolchain_specific_settings)),

            'source_files_lib': self.format_source_files('lib',tool_specific_settings, toolchain_specific_settings),

            'linker_file': self.linker_file or toolchain_specific_settings.linker_file or [
                tool_settings.linker_file for tool_settings in tool_specific_settings if tool_settings.linker_file],

            'macros': self.macros + list(flatten([
                settings.macros for settings in tool_specific_settings])) + toolchain_specific_settings.macros,

            'misc': [
                merge_recursive({k: v for settings in tool_specific_settings for k, v in settings.misc.items()},
                                toolchain_specific_settings.misc)],
            'project_dir': self.project_dir,

            'template': toolchain_specific_settings.template or [
                tool_settings.template for tool_settings in tool_specific_settings if tool_settings.template],
        }
        if d['linker_file'] == None and d['output_type'] == 'exe':
            raise RuntimeError("Executable - no linker command found.")

        if self.workspace.settings.generated_projects_dir != self.workspace.settings.generated_projects_dir_default:
            output_dir = self.workspace.settings.generated_projects_dir
            output_dir = output_dir.replace('$tool$', tool)
            output_dir = output_dir.replace('$project_name$', self.name)
            if self.target:
                output_dir = output_dir.replace('$target$', self.target)
        else:
            output_dir = os.path.join(self.project_dir['path'], "%s_%s" % (tool, self.name))
        d['output_dir']['path'] = os.path.normpath(output_dir)
        return d

    def fixup_executable(executable_path, tool):
        exporter = self.tools.get_value(tool, 'exporter')
        # ??? recursive call without self parameter ???
        fixup_executable(exporter, executable_path, tool)

    def _copy_files(self, file, output_dir, valid_files_group):
        file = os.path.normpath(file)
        dest_dir = os.path.join(os.getcwd(), output_dir, os.path.dirname(file))
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        if file.split('.')[-1] in valid_files_group:
            shutil.copy2(os.path.join(os.getcwd(), file), os.path.join(os.getcwd(), output_dir, file))

    def copy_files(self, proj_dic, tool):

        for path in proj_dic['include_paths']:
            path = os.path.normpath(path)
            files = os.listdir(path)
            dest_dir = os.path.join(os.getcwd(), proj_dic['output_dir']['path'], path)
            if not os.path.exists(dest_dir) and len(files):
                os.makedirs(dest_dir)
            for filename in files:
                if filename.split('.')[-1] in FILES_EXTENSIONS['include_paths']:
                    shutil.copy2(os.path.join(os.getcwd(), path, filename),
                                 os.path.join(os.getcwd(), proj_dic['output_dir']['path'], path))

        for k, v in proj_dic['source_files_c'][0].items():
            for file in v:
                self._copy_files(file, proj_dic['output_dir']['path'], FILES_EXTENSIONS['source_files_c'])

        for k, v in proj_dic['source_files_cpp'][0].items():
            for file in v:
                self._copy_files(file, proj_dic['output_dir']['path'], FILES_EXTENSIONS['source_files_cpp'])

        for k, v in proj_dic['source_files_s'][0].items():
            for file in v:
                self._copy_files(file, proj_dic['output_dir']['path'], FILES_EXTENSIONS['source_files_s'])

        for file in proj_dic['source_files_obj']:
            self._copy_files(file, proj_dic['output_dir']['path'], FILES_EXTENSIONS['source_files_obj'])

        for file in proj_dic['source_files_lib']:
            self._copy_files(file, proj_dic['output_dir']['path'], FILES_EXTENSIONS['source_files_lib'])

        linker = os.path.normpath(proj_dic['linker_file'])
        dest_dir = os.path.join(os.getcwd(), proj_dic['output_dir']['path'], os.path.dirname(linker))
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        shutil.copy2(os.path.join(os.getcwd(), linker),
                     os.path.join(os.getcwd(), proj_dic['output_dir']['path'], linker))
