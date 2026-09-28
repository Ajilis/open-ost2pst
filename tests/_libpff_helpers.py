NID_ROOT_FOLDER = 0x0122
NID_IPM_SUBTREE = 0x8022


def get_physical_root(store):
    root = store.get_root_folder()
    assert root is not None
    assert root.get_identifier() == NID_ROOT_FOLDER
    return root


def get_ipm_subtree(store):
    root = get_physical_root(store)
    for index in range(root.get_number_of_sub_folders()):
        child = root.get_sub_folder(index)
        if child.get_identifier() == NID_IPM_SUBTREE:
            return child
    raise AssertionError("IPM subtree not found")


def get_child_by_name(folder, name):
    for index in range(folder.get_number_of_sub_folders()):
        child = folder.get_sub_folder(index)
        if child.get_name() == name:
            return child
    raise AssertionError(f"subfolder not found: {name}")
