from blockfrost import ApiUrls, BlockFrostApi, ApiError
from pycardano import (
    PaymentSigningKey,
    PaymentVerificationKey,
    Address,
    Network,
    BlockFrostChainContext,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionBuilder,
    TransactionOutput,
)
from subprocess import check_output, CalledProcessError, STDOUT
import os
import string
import secrets
import time
import click
import sqlite3

__location__ = os.path.expanduser("~")
commits_db = "/commits.db"

numbers = string.digits
random = "".join(secrets.choice(numbers) for i in range(8))

@click.command()
@click.option(
    "--project-name",
    type=str,
    required=True,
    help="What you want your project name to be onchain.",
)
@click.option(
    "--git-repo-path", type=str, required=True, help="Path to your github repository."
)
@click.option(
    "--payment-signing-key-path",
    type=str,
    required=True,
    help="Path to your payment signing key.",
)
@click.option(
    "--network-type",
    type=str,
    required=True,
    help="The network you want to use, mainnet, preprod, etc.",
)
def main(project_name, git_repo_path, payment_signing_key_path, network_type):
    connection = ""
    network = ""
    payment_signing_key = PaymentSigningKey.load(payment_signing_key_path)
    payment_verification_key = PaymentVerificationKey.from_signing_key(
        payment_signing_key)
    api, network = get_network_attributes(network_type)
    from_address = str(Address(payment_verification_key.hash(), network=network))
    try:
        check_for_conflicts = check_output(
            ["git", "-C", f"{git_repo_path}", "diff", "main...origin/main"],
            stderr=STDOUT,
            encoding="UTF-8",
        )
        if len(check_for_conflicts) == 0:
            get_git_commit_info = check_output(
                [
                    "git",
                    "-C",
                    f"{git_repo_path}",
                    "log",
                    "-1",
                    "--date=default",
                    "--pretty=format:%C(auto)%H,%s,%ad",
                ],
                stderr=STDOUT,
                encoding="UTF-8",
            )
            commit_info = get_git_commit_info.split(",")
            local_commit_hash = commit_info[0]
            commit_message = commit_info[1]
            timestamp = commit_info[2]
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='commits';"
            )
            accounts_list = cursor.fetchall()
            if not accounts_list:
                with open("tables/commits_schema.sql") as f:
                    connection.executescript(f.read())
                with open("tables/transactions_schema.sql") as f:
                    connection.executescript(f.read())
                cursor.execute(
                    "INSERT INTO commits (onchain_id, project_name, local_commit_hash, commit_message, "
                    "commit_timestamp) VALUES (?, ?, ?, ?, ?)",
                    (
                        f"{random}",
                        f"{project_name}",
                        f"{local_commit_hash}",
                        f"{commit_message}",
                        f"{timestamp}",
                    ),
                )
                connection.commit()
                last_id = cursor.lastrowid
                create_metadata = get_metadata(
                    random, project_name, local_commit_hash, commit_message, timestamp
                )
                send_transaction(
                    from_address,
                    payment_signing_key,
                    create_metadata,
                    random,
                    local_commit_hash,
                    last_id,
                    network_type
                )
            else:
                onchain_id = connection.execute(
                    f"SELECT onchain_id FROM commits WHERE id=1"
                ).fetchone()
                duplicate = connection.execute(
                    f'SELECT local_commit_hash FROM commits WHERE local_commit_hash="{local_commit_hash}"'
                ).fetchall()
                if not duplicate:
                    cursor.execute(
                        "INSERT INTO commits (onchain_id, project_name, local_commit_hash, commit_message, "
                        "commit_timestamp) VALUES (?, ?, ?, ?, ?)",
                        (
                            f"{onchain_id[0]}",
                            f"{project_name}",
                            f"{local_commit_hash}",
                            f"{commit_message}",
                            f"{timestamp}",
                        ),
                    )
                    connection.commit()
                    create_metadata = get_metadata(
                        onchain_id[0],
                        project_name,
                        local_commit_hash,
                        commit_message,
                        timestamp,
                    )
                    print("You're good, sending transaction.")
                    last_id = cursor.lastrowid
                    send_transaction(
                        from_address,
                        payment_signing_key,
                        create_metadata,
                        onchain_id[0],
                        local_commit_hash,
                        last_id,
                        network_type
                    )
    except CalledProcessError as e:
        print(e.output)
        connection.close()
    finally:
        connection.close()


def get_db_connection():
    created_connection = sqlite3.connect("commits.db")
    created_connection.row_factory = sqlite3.Row
    return created_connection


def get_network_attributes(network_type):
    if network_type == "mainnet":
        api = BlockFrostApi(project_id=os.environ["PROJECT_ID"], base_url=ApiUrls.mainnet.value)
        if api.base_url == "https://cardano-mainnet.blockfrost.io/api":
            network = Network.MAINNET
    if network_type == "preprod":
        api = BlockFrostApi(project_id=os.environ["PROJECT_ID"], base_url=ApiUrls.preprod.value)
        if api.base_url == "https://cardano-preprod.blockfrost.io/api":
            network = Network.TESTNET
            return api, network

def get_metadata(
    onchain_id, project_name, local_commit_hash, commit_message, timestamp
):
    metadata = ""
    commit_message_length = string_byte_length(commit_message)
    if commit_message_length <= 64:
        metadata = {
            int(f"{onchain_id}"): {
                "msg": [
                    f"{project_name}",
                    f"{local_commit_hash}",
                    f"{commit_message}",
                    f"{timestamp}",
                ]
            }
        }
    elif commit_message_length > 64:
        commit_message_part_one, commit_message_part_two = (
            commit_message[: len(commit_message) // 2],
            commit_message[len(commit_message) // 2:],
        )
        metadata = {
            int(f"{onchain_id}"): {
                "msg": [
                    f"{project_name}",
                    f"{local_commit_hash}",
                    f"{commit_message_part_one}",
                    f"{commit_message_part_two}",
                    f"{timestamp}",
                ]
            }
        }
    elif commit_message_length > 128:
        print(
            "gitgood only supports commit strings up to 128 bytes, please amend the commit message."
        )
    return metadata


def send_transaction(
    from_address, payment_signing_key, created_metadata, onchain_id, local_commit_hash, last_id, network_type
):
    context = BlockFrostChainContext(
        os.environ["PROJECT_ID"], base_url=ApiUrls.preprod.value
    )
    auxiliary_data = AuxiliaryData(AlonzoMetadata(metadata=Metadata(created_metadata)))
    utxos = context.utxos(from_address)
    builder = TransactionBuilder(context)
    builder.add_input(utxos[0])
    builder.add_input_address(from_address)
    builder.auxiliary_data = auxiliary_data
    to_address = from_address
    builder.add_output(TransactionOutput.from_primitive([to_address, 2000000]))
    signed_tx = builder.build_and_sign(
        [payment_signing_key], change_address=from_address
    )
    submit = context.submit_tx(signed_tx)
    get_connection = get_db_connection()
    cursor = get_connection.cursor()
    cursor.execute(
                    "INSERT INTO transactions (transaction_id, transaction_hash) VALUES (?, ?)",
                    (
                        f"{last_id}",
                        f"{submit}",
                    ),
                )
    get_connection.commit()
    print(
        f" Transaction sent! Check the transaction here: https://preprod.cardanoscan.io/transaction/{submit}."
    )
    print(
        "Please note there will be a slight delay for the transaction to show up on chain. Waiting a bit before "
        "verification. "
    )
    get_connection.close()
    time.sleep(80)
    verify_commits_onchain(onchain_id, local_commit_hash, network_type)


def verify_commits_onchain(onchain_id, local_commit_hash, network_type):
    api, network = get_network_attributes(network_type)
    try:
        onchain_commits = api.metadata_label_json(onchain_id, return_type="json")
        for commit in onchain_commits:
            onchain_commit_hash = commit["json_metadata"]["msg"][1]
            if onchain_commit_hash == local_commit_hash:
                print(
                    "Latest local commit and onchain commit matches, everything is awesome."
                )
            else:
                print(
                    "Not the latest commit, commit is not onchain yet, or local repo is out of sync."
                )
    except ApiError:
        print(
            "Commit is not onchain yet"
        )


def string_byte_length(s):
    return len(s.encode("utf-8"))


if __name__ == "__main__":
    main()
