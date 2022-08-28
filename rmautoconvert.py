#!/usr/bin/env python3

#
# requires:
# pip install git+https://github.com/naturale0/rmrl.git
#
# Use Python 3.8 compatible syntax on purpose.

import sys
from json import load
from os import listdir, stat, utime, unlink, mkdir
from os.path import join, isdir
from shutil import rmtree
import re
from datetime import datetime, timezone
from typing import Optional
from rmrl import render


class Element(object):
    def __init__(self, element_id: str, name: str, last_modified: Optional[datetime], parent_id: Optional[str] = None, is_document: bool = False):
        self.parent = None
        self.children = set()
        self.children_ids = set()
        self.id = element_id
        self.name = name
        self.sanitized_name = sanitize_filename(name.lower())
        self.filename = None
        self.parent_id = parent_id
        self.parent = None
        self.last_modified = last_modified
        self.is_document = is_document

    def __repr__(self):
        return f"{self.id}: {self.name} (last modified {self.last_modified}) (on disk: {self.filename}) -> {self.children}"

    def __eq__(self, other):
        if isinstance(other, Element):
            return self.id == other.id
        return False

    def __ne__(self, other):
        if isinstance(other, Element):
            return self.id != other.id
        return False

    def __hash__(self):
        return hash(self.id)


def sanitize_filename(fname: str) -> str:
    return re.sub(r'[^0-9a-z-_]', '_', fname)


def read_all_elements(all_elements: dict, basepath: str, element_id: str):
    with open(f'{join(basepath, element_id)}.metadata') as f:
        meta_obj = load(f)
    if meta_obj["deleted"]:
        return None
    parent_id = meta_obj.get("parent", None)
    if parent_id is not None and parent_id == "trash":
        # skip deleted files
        return
    dt = datetime.fromtimestamp(int(meta_obj["lastModified"])//1000, tz=timezone.utc)
    all_elements[element_id] = Element(element_id, meta_obj["visibleName"], dt, parent_id, meta_obj["type"] == "DocumentType")


def build_tree(all_elements: dict, root_element: Element):
    for element_id, element in all_elements.items():
        if element.parent_id is not None and element.parent_id != "":
            if element.parent_id != "trash":
                all_elements[element_id].parent = all_elements[element.parent_id]
                all_elements[element.parent_id].children.add(all_elements[element_id])
                all_elements[element.parent_id].children_ids.add(element_id)
        else:
            all_elements[element_id].parent_id = root_element.id
            all_elements[element_id].parent = root_element
            root_element.children.add(all_elements[element_id])
            root_element.children_ids.add(element_id)


def pdf_tree(current_path: str, all_elements: dict, root_element: Element, to_delete: list):
    files = listdir(current_path)
    for fname in files:
        # there is only 2 cases:
        # - a pdf
        # - a directory
        # name is always <sanitized_name>_<uuid> resp. <sanitizied_name>_<uuid>.pdf
        m = r'^([0-9a-z-_]+)_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'
        is_document = False
        if fname.endswith(".pdf"):
            m = r'^([0-9a-z-_]+)_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.pdf$'
            is_document = True
        match = re.match(m, fname)
        if match is None or len(match.groups()) != 2:
            # something completely strange (or "." / "..") - do not touch
            continue
        fullname = join(current_path, fname)
        if (isdir(fullname) and is_document) or (not isdir(fullname) and not is_document):
            to_delete.append(fullname)
            continue

        sanitized_name = match.group(1)
        element_id = match.group(2)

        info = stat(fullname)
        dt = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc)

        # check if it matches any of the elements
        current_element = all_elements.get(element_id, None)
        if current_element is not None:
            # yes, it is there. but is it in the current root and has the correct name?
            if (current_element.id not in root_element.children_ids) or (current_element.parent_id != root_element.id) or (sanitized_name != current_element.sanitized_name) or (dt != current_element.last_modified and is_document):
                # it is not... so the easiest is to delete it and recreate in the next step
                to_delete.append(fullname)
            else:
                current_element.filename = fullname
                if isdir(fullname):
                    pdf_tree(fullname, all_elements, current_element, to_delete)
        else:
            # it is not there. that means we can delete it.
            to_delete.append(fullname)


def create_pdfs(current_element: Element, current_path: str):
    now = datetime.utcnow()
    if current_element.filename is None:
        if current_element.is_document:
            current_filename = f"{join(current_path, current_element.sanitized_name)}_{current_element.id}.pdf"
            with render(f"{join(sys.argv[1], current_element.id)}.metadata") as res:
                with open(current_filename, "wb") as f:
                    f.write(res.read())
                    # f.write(render(f"{join(sys.argv[1], current_element.id)}.metadata"))
            times = (now.timestamp(), current_element.last_modified.timestamp())
            utime(current_filename, times)
            current_element.filename = current_filename
        else:
            current_filename = join(current_path, f"{current_element.sanitized_name}_{current_element.id}")
            mkdir(current_filename)
            # times = (mktime(now.timetuple()), mktime(current_element.last_modified.timetuple()))
            times = (now.timestamp(), current_element.last_modified.timestamp())
            utime(current_filename, times)
            current_element.filename = current_filename
            for child_element in current_element.children:
                create_pdfs(child_element, current_filename)
    else:
        if not current_element.is_document:
            for child_element in current_element.children:
                create_pdfs(child_element, current_element.filename)


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    files = listdir(sys.argv[1])
    all_elements = dict()
    for fname in files:
        if fname.endswith(".metadata"):
            read_all_elements(all_elements, sys.argv[1], fname[:-9])
    root_element = Element("root", "root", None)
    root_element.filename = sys.argv[2]
    build_tree(all_elements, root_element)

    # to lists to store the pdfs to be deleted
    to_delete = list()

    # pass 2: read the pdfs
    pdf_tree(sys.argv[2], all_elements, root_element, to_delete)

    for fname in to_delete:
        if fname.endswith(".pdf"):
            unlink(fname)
        else:
            rmtree(fname, ignore_errors=True)

    # now:
    # iterate through all the elements and check if filename is set.
    create_pdfs(root_element, sys.argv[2])
