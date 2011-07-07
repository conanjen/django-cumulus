import cloudfiles
import mimetypes
from cloudfiles.errors import NoSuchObject, ResponseError

from django.core.files import File
from django.core.files.storage import Storage

from .settings import CUMULUS


class CloudFilesStorage(Storage):
    """
    Custom storage for Rackspace Cloud Files.
    """
    default_quick_listdir = True

    def __init__(self, username=None, api_key=None, container=None, timeout=None,
                 connection_kwargs=None):
        """
        Initialize the settings for the connection and container.
        """
        self.api_key = api_key or CUMULUS['API_KEY']
        self.auth_url = CUMULUS['AUTH_URL']
        self.connection_kwargs = connection_kwargs or {}
        self.container_name = container or CUMULUS['CONTAINER']
        self.timeout = timeout or CUMULUS['TIMEOUT']
        self.use_servicenet = CUMULUS['SERVICENET']
        self.username = username or CUMULUS['USERNAME']


    def __getstate__(self):
        """
        Return a picklable representation of the storage.
        """
        return dict(username=self.username,
                    api_key=self.api_key,
                    container_name=self.container_name,
                    timeout=self.timeout,
                    use_servicenet=self.use_servicenet,
                    connection_kwargs=self.connection_kwargs)

    def _get_connection(self):
        if not hasattr(self, '_connection'):
            self._connection = cloudfiles.get_connection(
                                  username=self.username,
                                  api_key=self.api_key,
                                  authurl = self.auth_url,
                                  timeout=self.timeout,
                                  servicenet=self.use_servicenet,
                                  **self.connection_kwargs)
        return self._connection

    def _set_connection(self, value):
        self._connection = value

    connection = property(_get_connection, _set_connection)

    def _get_container(self):
        if not hasattr(self, '_container'):
            self.container = self.connection.get_container(
                                                        self.container_name)
        return self._container

    def _set_container(self, container):
        """
        Set the container, making it publicly available if it is not already.
        """
        if not container.is_public():
            container.make_public()
        if hasattr(self, '_container_public_uri'):
            delattr(self, '_container_public_uri')
        self._container = container

    container = property(_get_container, _set_container)

    def _get_container_url(self):
        if not hasattr(self, '_container_public_uri'):
            self._container_public_uri = self.container.public_uri()
        if CUMULUS['CNAMES'] and self._container_public_uri in CUMULUS['CNAMES']:
            self._container_public_uri = CUMULUS['CNAMES'][self._container_public_uri]
        return self._container_public_uri

    container_url = property(_get_container_url)

    def _get_cloud_obj(self, name):
        """
        Helper function to get retrieve the requested Cloud Files Object.
        """
        return self.container.get_object(name)

    def _open(self, name, mode='rb'):
        """
        Return the CloudFilesStorageFile.
        """
        return CloudFilesStorageFile(storage=self, name=name)

    def _save(self, name, content):
        """
        Use the Cloud Files service to write ``content`` to a remote file
        (called ``name``).
        """
        content.open()
        cloud_obj = self.container.create_object(name)
        if hasattr(content.file, 'size'):
            cloud_obj.size = content.file.size
        else:
            cloud_obj.size = content.size
        # If the content type is available, pass it in directly rather than
        # getting the cloud object to try to guess.
        if hasattr(content.file, 'content_type'):
            cloud_obj.content_type = content.file.content_type
        elif hasattr(content, 'content_type'):
            cloud_obj.content_type = content.content_type
        else:
            mime_type, encoding = mimetypes.guess_type(name)
            cloud_obj.content_type = mime_type
        cloud_obj.send(content)
        content.close()
        return name

    def delete(self, name):
        """
        Deletes the specified file from the storage system.
        """
        try:
            self.container.delete_object(name)
        except ResponseError, exc:
            if exc.status == 404:
                pass
            else:
                raise

    def exists(self, name):
        """
        Returns True if a file referenced by the given name already exists in
        the storage system, or False if the name is available for a new file.
        """
        try:
            self._get_cloud_obj(name)
            return True
        except NoSuchObject:
            return False

    def listdir(self, path):
        """
        Lists the contents of the specified path, returning a 2-tuple; the
        first being an empty list of directories (not available for quick-
        listing), the second being a list of filenames.

        If the list of directories is required, use the full_listdir method.
        """
        files = []
        if path and not path.endswith('/'):
            path = '%s/' % path
        path_len = len(path)
        for name in self.container.list_objects(path=path):
            files.append(name[path_len:])
        return ([], files)

    def full_listdir(self, path):
        """
        Lists the contents of the specified path, returning a 2-tuple of lists;
        the first item being directories, the second item being files.

        On large containers, this may be a slow operation for root containers
        because every single object must be returned (cloudfiles does not
        provide an explicit way of listing directories).
        """
        dirs = set()
        files = []
        if path and not path.endswith('/'):
            path = '%s/' % path
        path_len = len(path)
        for name in self.container.list_objects(prefix=path):
            name = name[path_len:]
            slash = name[1:-1].find('/') + 1
            if slash:
                dirs.add(name[:slash])
            elif name:
                files.append(name)
        dirs = list(dirs)
        dirs.sort()
        return (dirs, files)

    def size(self, name):
        """
        Returns the total size, in bytes, of the file specified by name.
        """
        return self._get_cloud_obj(name).size

    def url(self, name):
        """
        Returns an absolute URL where the file's contents can be accessed
        directly by a web browser.
        """
        return '%s/%s' % (self.container_url, name)


class CloudFilesStorageFile(File):
    closed = False

    def __init__(self, storage, name, *args, **kwargs):
        self._storage = storage
        self._pos = 0
        super(CloudFilesStorageFile, self).__init__(file=None, name=name,
                                                    *args, **kwargs)

    def _get_pos(self):
        return self._pos

    def _get_size(self):
        if not hasattr(self, '_size'):
            self._size = self._storage.size(self.name)
        return self._size

    def _set_size(self, size):
        self._size = size

    size = property(_get_size, _set_size)

    def _get_file(self):
        if not hasattr(self, '_file'):
            self._file = self._storage._get_cloud_obj(self.name)
            self._file.tell = self._get_pos
        return self._file

    def _set_file(self, value):
        if value is None:
            if hasattr(self, '_file'):
                del self._file
        else:
            self._file = value

    file = property(_get_file, _set_file)

    def read(self, num_bytes=None):
        data = self.file.read(size=num_bytes or -1, offset=self._pos)
        self._pos += len(data)
        return data

    def open(self, *args, **kwargs):
        """
        Open the cloud file object.
        """
        self._pos = 0

    def close(self, *args, **kwargs):
        self._pos = 0

    @property
    def closed(self):
        return not hasattr(self, '_file')

    def seek(self, pos):
        self._pos = pos
