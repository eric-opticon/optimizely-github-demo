"""
A quick-and-dirty integration of GitHub service hooks and Optimizely's Experiment API.
"""


import json
import logging
import os
import sys

import flask
import requests
import rq

import worker


GITHUB_URL = 'https://raw.githubusercontent.com/eric-opticon/eric-opticon.herokuapp.com/%(branch)s/%(filename)s'
GITHUB_API_URL = 'https://api.github.com/repos/eric-opticon/eric-opticon.herokuapp.com/contents/js/experiments/'
REST_API_URL = 'https://www.optimizelyapis.com/experiment/v1'
REST_HEADERS = {
    'content-type': 'application/json',
    # TODO(you): Add your Optimizely Experiment API token here.
    'token': 'REPLACE WITH YOUR OPTIMIZELY TOKEN',
}


def update_experiment(experiment):
  """Update the Experiment with the provided payload.
  
  Args:
    experiment: A dictionary representation of the Experiment to be updated.

  Returns:
    A dictionary of the server response body after updating the Experiment.
  """
  path = '/experiments/%d' % experiment['id']
  url = REST_API_URL + path
  logging.info('PUT %s', url)
  logging.info(experiment)
  resp = requests.put(url, data=json.dumps(experiment), headers=REST_HEADERS, verify=False)
  logging.info('status: %d body: %s',resp.status_code, resp.text)
  return resp.json()


def get_experiments(project_id, filters=None):
  """Get the Project Experiments.
  
  Args:
    project_id: The Project ID of the Experiments to be fetched.
    filters: An optional filter for the list of Experiments.

  Returns:
    The list of Experiment dictionaries.
  """
  # Convert a list of tuples into a list of parameter tuples.
  params = [('filter', '%s:%s' % (x, y)) for x, y in filters]
  url = REST_API_URL + '/projects/%d/experiments/' % project_id
  logging.info('GET %s', url)
  logging.info(params)
  resp = requests.get(url, params=params, headers=REST_HEADERS, verify=False)
  logging.info('status: %d body: %s',resp.status_code, resp.text)
  return resp.json()


def get_experiment(experiment_id):
  """Get an Experiment by ID.

  Args:
    experiment_id: The ID of the Experiment to be fetched.

  Returns:
    An Experiment dictionary.
  """
  path = '/experiments/%d' % experiment_id
  url = REST_API_URL + path
  logging.info('GET %s', url)
  resp = requests.get(url, headers=REST_HEADERS, verify=False)
  logging.info('status: %d body: %s',resp.status_code, resp.text)
  return resp.json()


def get_variations(experiment_id):
  """Get the Experiment Variations.
  
  Args:
    experiment_id: The Experiment ID of the Variations to be fetched.

  Returns:
    The list of Variation dictionaries.
  """
  path = '/experiments/%d/variations/' % experiment_id
  url = REST_API_URL + path
  logging.info('GET %s', url)
  resp = requests.get(url, headers=REST_HEADERS, verify=False)
  logging.info('status: %d body: %s',resp.status_code, resp.text)
  return resp.json()


def update_variation(variation):
  """Update the Variation with the provided payload.
  
  Args:
    experiment: A dictionary representation of the Variation to be updated.

  Returns:
    A dictionary of the server response body after updating the Variation.
  """
  path = '/variations/%d' % variation['id']
  url = REST_API_URL + path
  logging.info('PUT %s', url)
  logging.info(variation)
  resp = requests.put(url, data=json.dumps(variation), headers=REST_HEADERS, verify=False)
  logging.info('status: %d body: %s',resp.status_code, resp.text)
  if resp.status_code > 299:
    raise Exception('Failed to update variation')
  return resp.json()


def filename_to_variation(filename, variation=None, branch='master'):
  """Fetches the contents of a Variation from GitHub by filename.
  
  Args:
    filename: The filename to be fetched from GitHub.
    variation: An optional Variation dictionary to apply the file contents too
    branch: An optional git branch name (master by default).

  Returns:
    A Variation dictionary with the contents of the file.
  """
  # Fetch the content from GitHub.
  gh_params = {
    'branch': branch,
    'filename': filename,
  }
  url = GITHUB_URL % gh_params
  logging.info('GET %s', url)
  resp = requests.get(url, headers={'content-type': 'application/json'}, verify=False)
  logging.info('Github responded with %d', resp.status_code)
  if resp.status_code != 200:
    raise Exception('Github responded with %d' % resp.status_code)
  # Use the existing/provided `variation` or create a new one.
  variation = variation or {'is_paused': False, 'weight': 0}
  # Set the contents.
  #variation['description'] = filename
  variation['js_component'] = resp.text
  return variation


def get_variation_filenames(experiment_name):
  """Get a list of filenames for a given Experiment name.
  
  Args:
    experiment_name: The name of the Experiment, which should coorespond to a directory in the GH repo.

  Returns:
    A list of Variation filenames that exist under the Experiment directory.
  """
  resp = requests.get(GITHUB_API_URL + experiment_name, verify=False)
  return [x['name'] for x in resp.json()]


def process_commits(project_id, experiment_id, commits):
  """Parse a list of GitHub commits and update the Experiments and Variations it contains, if any.
  
  Args:
    project_id: The Project ID.
    experiment_id: The Experiment ID.
    commits: A list of git commits, provided by GitHub's API.
  """
  # Get the variation filenames (added, updated, removed, if possible).
  commit_filenames = {
    'added': [],
    'modified': [],
    'removed': [],
  }
  # Parse the filenames from the commits.
  logging.info('looping commits...')
  for commit in commits:
    for key in commit_filenames.iterkeys():
      commit_filenames[key].extend([x for x in commit[key] if 'js/experiments/' in x])
      commit_filenames[key] = list(set(commit_filenames[key]))

  # Fetch the Experiment.
  logging.info('done. Getting experiment...')
  experiment = get_experiment(experiment_id)

  logging.info('done. Getting filenames...')
  # Note(eric): I'm not actually sure why I did this.
  some_match = commit_filenames.get('added') or commit_filenames.get('modified') or commit_filenames.get('removed')

  # Get the Experiment name.
  experiment_name = some_match[0].replace('js/experiments/', '').split('/')[0]
  repo_filenames = get_variation_filenames(experiment_name)

  # Fetch the Experiment Variations.
  logging.info('done. Getting variations...')
  variations = get_variations(experiment['id'])

  # Create a list of Variation filenames.
  logging.info('done. Parsing filenames...')
  fn_path = 'js/experiments/%s/' % experiment_name
  variation_names = sorted([fn_path + x for x in repo_filenames])
  logging.info('variation_names: %s', variation_names)
  logging.info('create variations')

  # TODO: Create variations found in commit_filenames['added'].
  # TODO: Delete variations found in commit_filenames['removed'].
  # Update variations.

  # Pair filenames with Variation IDs.
  id_var_pairs = zip(experiment['variation_ids'], variation_names)
  logging.info('id_var_pairs: %s', id_var_pairs)
  logging.info('update_variations')

  # Iterate over the id,name Variation pairs and update the Variation contents.
  for v_id, v_name in id_var_pairs:
    logging.info('Variation id: %d name: %s', v_id, v_name)
    # Try to match the ID in the filename to an existing Variation ID.
    matches = [x for x in variations if x['id'] == v_id]
    if not matches:
      logging.info('no matches')
      continue
    # Use the matched Variation.
    variation = matches[0]
    variation = filename_to_variation(v_name, variation)
    # Update the Variation contents through the Optimizely API.
    variation = update_variation(variation)

  logging.info('variations are ready, start the experiment!')
  # Start the Experiment.
  experiment['status'] = 'Running'
  experiment['activation_mode'] = 'immediate'
  experiment = update_experiment(experiment)
  logging.info('finished')


app = flask.Flask(__name__)
q = rq.Queue(connection=worker.conn)


@app.route('/')
def index():
  """Render an HTML page. This happens to be the page which is using Optimizely."""
  values = {
    'message': 'Hello world!',
  }
  return flask.render_template('index.html', **values)


@app.route('/_hooks', methods=['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'])
def hooks():
  """Webhook for integration with the GitHub API."""
  project_id = 860940042
  experiment_id = 855363189
  json_body = getattr(flask.request, 'json', {})
  commits = json_body.get('commits')
  if not commits:
    return json.dumps({
      'message': 'Nothing to do',
    })

  logging.info('enqueuing...')
  result = q.enqueue(process_commits, project_id, experiment_id, commits)
  logging.info('done.')

  return json.dumps({
    'message': 'thanks for all the fish',
  })


@app.route('/favicon.ico')
def favicon():
  """Handle requests for the favicon to prevent 404s."""
  return None
